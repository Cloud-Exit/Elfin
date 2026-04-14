#!/usr/bin/env python3
"""Elfin hardware image preparation and flash tool.

Takes a blank disk attached to the host, produces a bootable Elfin disk for
Turing RK1 (RK3588). Implements PRD `plans/elfin-hardware-install-prd.md`.

Python 3 stdlib only. Run as root on Linux. macOS unsupported in v1.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# PINS — bump these together when upgrading upstream artifacts.
# ---------------------------------------------------------------------------

IMAGE_URL = (
    "https://firmware.turingpi.com/turing-rk1/ubuntu_22.04_rockchip_linux/"
    "v1.33/ubuntu-22.04-preinstalled-server-arm64-turing-rk1.img.xz"
)
IMAGE_FILENAME = "ubuntu-22.04-preinstalled-server-arm64-turing-rk1.img.xz"
# Placeholder — must be filled before production use. The script refuses to
# run against a live target unless every pin is set or --allow-unpinned is
# passed (tests/dev only).
IMAGE_SHA256: Optional[str] = None

UROCK_REPO = "https://github.com/Joshua-Riek/ubuntu-rockchip.git"
UROCK_COMMIT: Optional[str] = None  # Placeholder — pin before production use.

BUN_VERSION: Optional[str] = None  # e.g. "1.1.30"; aarch64 binary fetched from GitHub releases.
BUN_SHA256: Optional[str] = None

MIN_TARGET_DISK_BYTES = 64 * 1024 * 1024 * 1024  # 64 GiB

# Paths inside the seeded rootfs.
SEED_APP_DIR = "/opt/elfin"
SEED_BOOTSTRAP_PATH = "/opt/elfin/data/bootstrap.json"
SEED_UNIT_PATH = "/etc/systemd/system/elfin.service"
SEED_BUN_PATH = "/usr/local/bin/bun"

# Files/dirs excluded from the seed rsync.
SEED_EXCLUDES = [
    ".git",
    "node_modules",
    ".bun-cache",
    "__pycache__",
    "*.pyc",
    ".venv",
    "venv",
    "tools/.logs",
    "data/models/*.gguf.tmp",
]

# Host tools the script expects to find in $PATH.
REQUIRED_TOOLS_LINUX = [
    "losetup",
    "mount",
    "umount",
    "parted",
    "rsync",
    "xz",
    "curl",
    "sha256sum",
    "lsblk",
    "blockdev",
    "chroot",
    "git",
]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class StepLogger:
    """Timestamped step logger. Mirrors to stderr and a rolling log file."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = log_path.open("a", encoding="utf-8")

    def log(self, step: str, msg: str) -> None:
        line = f"[{_iso_now()}] [{step}] {msg}"
        print(line, file=sys.stderr, flush=True)
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Pure helpers — unit-testable without root or real devices.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DiskCandidate:
    name: str
    path: str
    size_bytes: int
    model: str
    mountpoints: tuple[str, ...]

    def is_mounted(self) -> bool:
        return any(mp for mp in self.mountpoints if mp)


def parse_lsblk_json(data: str) -> list[DiskCandidate]:
    """Parse `lsblk -J -b -o NAME,SIZE,MODEL,TYPE,MOUNTPOINTS,PATH` output."""
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid lsblk JSON: {exc}") from exc

    out: list[DiskCandidate] = []
    for dev in payload.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        mps = _collect_mountpoints(dev)
        out.append(
            DiskCandidate(
                name=dev.get("name", ""),
                path=dev.get("path") or f"/dev/{dev.get('name', '')}",
                size_bytes=int(dev.get("size") or 0),
                model=(dev.get("model") or "").strip(),
                mountpoints=tuple(mps),
            )
        )
    return out


def _collect_mountpoints(dev: dict) -> list[str]:
    mps: list[str] = []
    raw = dev.get("mountpoints") or [dev.get("mountpoint")]
    for mp in raw or []:
        if mp:
            mps.append(mp)
    for child in dev.get("children") or []:
        mps.extend(_collect_mountpoints(child))
    return mps


def find_root_disk(proc_mounts: str) -> Optional[str]:
    """Given /proc/mounts content, return the block device backing `/`."""
    for line in proc_mounts.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "/":
            return _strip_partition_suffix(parts[0])
    return None


def _strip_partition_suffix(dev: str) -> str:
    """`/dev/sda1` -> `/dev/sda`, `/dev/nvme0n1p3` -> `/dev/nvme0n1`."""
    if not dev.startswith("/dev/"):
        return dev
    name = dev[len("/dev/"):]
    if name.startswith("nvme") or name.startswith("mmcblk"):
        # nvme0n1p3, mmcblk0p1 — strip trailing `p<digits>`
        idx = name.rfind("p")
        if idx > 0 and name[idx + 1 :].isdigit():
            return "/dev/" + name[:idx]
        return "/dev/" + name
    # sda1 -> sda
    stripped = name.rstrip("0123456789")
    return "/dev/" + stripped


def validate_target_disk(
    disk: DiskCandidate,
    root_disk_path: Optional[str],
    min_size_bytes: int = MIN_TARGET_DISK_BYTES,
) -> Optional[str]:
    """Return a human-readable error if disk is unsafe, else None."""
    if root_disk_path and disk.path == root_disk_path:
        return f"{disk.path} is the host root disk"
    if disk.is_mounted():
        return f"{disk.path} has mounted partitions: {', '.join(m for m in disk.mountpoints if m)}"
    if disk.size_bytes < min_size_bytes:
        return (
            f"{disk.path} is too small ({disk.size_bytes} bytes, "
            f"need at least {min_size_bytes})"
        )
    return None


def verify_sha256(path: Path, expected: str) -> bool:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected.lower()


def check_tools_present(tools: list[str]) -> list[str]:
    """Return names of tools missing from $PATH."""
    return [t for t in tools if shutil.which(t) is None]


def check_pins(allow_unpinned: bool) -> list[str]:
    """Return list of unset pins. Caller decides whether that's fatal."""
    missing = []
    if IMAGE_SHA256 is None:
        missing.append("IMAGE_SHA256")
    if UROCK_COMMIT is None:
        missing.append("UROCK_COMMIT")
    if BUN_VERSION is None:
        missing.append("BUN_VERSION")
    if BUN_SHA256 is None:
        missing.append("BUN_SHA256")
    return missing


# ---------------------------------------------------------------------------
# Platform guards
# ---------------------------------------------------------------------------


def require_linux() -> None:
    if platform.system() != "Linux":
        raise SystemExit(
            f"macOS and other non-Linux hosts are not supported in v1 "
            f"(detected: {platform.system()}). Run on a Linux host."
        )


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("prepare_image.py must be run as root (or via sudo).")


# ---------------------------------------------------------------------------
# Host doctor
# ---------------------------------------------------------------------------


def host_doctor(log: StepLogger, allow_unpinned: bool) -> None:
    log.log("doctor", f"python {sys.version.split()[0]}, platform {platform.system()}")
    require_linux()
    missing = check_tools_present(REQUIRED_TOOLS_LINUX)
    if missing:
        raise SystemExit(f"missing required host tools: {', '.join(missing)}")
    missing_pins = check_pins(allow_unpinned)
    if missing_pins and not allow_unpinned:
        raise SystemExit(
            "upstream pins not set: "
            + ", ".join(missing_pins)
            + ". Edit PINS block in tools/prepare_image.py or pass "
            "--allow-unpinned for local dev only."
        )
    if missing_pins:
        log.log("doctor", f"WARNING unpinned artifacts: {', '.join(missing_pins)}")
    log.log("doctor", "host checks passed")


# ---------------------------------------------------------------------------
# Image fetcher
# ---------------------------------------------------------------------------


class ImageFetcher:
    def __init__(self, log: StepLogger, cache_dir: Path) -> None:
        self.log = log
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self) -> Path:
        dest = self.cache_dir / IMAGE_FILENAME
        if IMAGE_SHA256 and dest.exists() and verify_sha256(dest, IMAGE_SHA256):
            self.log.log("fetch", f"cache hit {dest}")
            return dest
        if dest.exists():
            self.log.log("fetch", f"cache miss or stale, removing {dest}")
            dest.unlink()
        self.log.log("fetch", f"downloading {IMAGE_URL}")
        _download(IMAGE_URL, dest)
        if IMAGE_SHA256 and not verify_sha256(dest, IMAGE_SHA256):
            raise SystemExit(f"sha256 mismatch on downloaded image {dest}")
        self.log.log("fetch", f"fetched {dest} ({dest.stat().st_size} bytes)")
        return dest


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as resp, tmp.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.rename(dest)


# ---------------------------------------------------------------------------
# Image mounter — loop device + partition mount
# ---------------------------------------------------------------------------


class LoopMount:
    """Context manager for loop-mounting a .img (or decompressed .img.xz)."""

    def __init__(self, log: StepLogger, image_xz: Path, workdir: Path) -> None:
        self.log = log
        self.image_xz = image_xz
        self.workdir = workdir
        self.image_raw: Optional[Path] = None
        self.loop_dev: Optional[str] = None
        self.root_mount: Optional[Path] = None
        self.boot_mount: Optional[Path] = None

    def __enter__(self) -> "LoopMount":
        self.image_raw = self._decompress()
        self.loop_dev = self._attach_loop(self.image_raw)
        self._mount_partitions()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._cleanup()

    def _decompress(self) -> Path:
        raw = self.workdir / IMAGE_FILENAME.removesuffix(".xz")
        if raw.exists():
            self.log.log("mount", f"decompressed image already present {raw}")
            return raw
        self.log.log("mount", f"decompressing {self.image_xz} -> {raw}")
        with self.image_xz.open("rb") as src, raw.open("wb") as dst:
            subprocess.run(["xz", "-dc"], stdin=src, stdout=dst, check=True)
        return raw

    def _attach_loop(self, raw: Path) -> str:
        out = subprocess.check_output(
            ["losetup", "--show", "-Pf", str(raw)], text=True
        ).strip()
        self.log.log("mount", f"attached loop {out}")
        return out

    def _mount_partitions(self) -> None:
        assert self.loop_dev is not None
        root_mp = self.workdir / "rootfs"
        boot_mp = self.workdir / "bootfs"
        root_mp.mkdir(exist_ok=True)
        boot_mp.mkdir(exist_ok=True)
        # Rockchip image convention: partition 1 = boot/efi/uboot, last = root.
        # Use parted to enumerate; pick largest as root.
        parts = self._list_partitions(self.loop_dev)
        if not parts:
            raise SystemExit(f"no partitions found on {self.loop_dev}")
        root_part = max(parts, key=lambda p: p[1])[0]
        boot_part = parts[0][0]
        subprocess.run(["mount", root_part, str(root_mp)], check=True)
        self.root_mount = root_mp
        if boot_part != root_part:
            subprocess.run(["mount", boot_part, str(boot_mp)], check=True)
            self.boot_mount = boot_mp
        self.log.log("mount", f"root={root_part} boot={boot_part}")

    def _list_partitions(self, loop_dev: str) -> list[tuple[str, int]]:
        """Return (partition_path, size_bytes) for each partition on loop."""
        out = subprocess.check_output(
            ["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,PATH", loop_dev], text=True
        )
        payload = json.loads(out)
        result: list[tuple[str, int]] = []
        for dev in payload.get("blockdevices", []):
            for child in dev.get("children", []) or []:
                if child.get("type") == "part":
                    result.append(
                        (
                            child.get("path") or f"/dev/{child.get('name', '')}",
                            int(child.get("size") or 0),
                        )
                    )
        return result

    def _cleanup(self) -> None:
        for mp in (self.boot_mount, self.root_mount):
            if mp and mp.is_mount():
                try:
                    subprocess.run(["umount", str(mp)], check=False)
                    self.log.log("mount", f"unmounted {mp}")
                except Exception as e:
                    self.log.log("mount", f"umount {mp} failed: {e}")
        if self.loop_dev:
            try:
                subprocess.run(["losetup", "-d", self.loop_dev], check=False)
                self.log.log("mount", f"detached {self.loop_dev}")
            except Exception as e:
                self.log.log("mount", f"losetup -d {self.loop_dev} failed: {e}")


# ---------------------------------------------------------------------------
# Seeder — copy Elfin tree, write systemd unit, drop bootstrap marker
# ---------------------------------------------------------------------------


class Seeder:
    def __init__(self, log: StepLogger, rootfs: Path, source_tree: Path) -> None:
        self.log = log
        self.rootfs = rootfs
        self.source_tree = source_tree

    def run(self) -> None:
        self._copy_app_tree()
        self._write_bootstrap()
        self._write_systemd_unit()
        self._enable_systemd_unit()
        self._place_bun_binary()
        self.log.log("seed", "seed complete")

    def _copy_app_tree(self) -> None:
        target = self.rootfs / SEED_APP_DIR.lstrip("/")
        target.mkdir(parents=True, exist_ok=True)
        args = ["rsync", "-aH", "--delete"]
        for pat in SEED_EXCLUDES:
            args.extend(["--exclude", pat])
        args.append(str(self.source_tree) + "/")
        args.append(str(target) + "/")
        self.log.log("seed", f"rsync {self.source_tree} -> {target}")
        subprocess.run(args, check=True)

    def _write_bootstrap(self) -> None:
        path = self.rootfs / SEED_BOOTSTRAP_PATH.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "admin_username": "admin",
            "admin_password": "admin",
            "force_password_change": True,
            "seeded_at": _iso_now(),
        }
        path.write_text(json.dumps(payload, indent=2))
        # World-unreadable: password is literal in v1.
        path.chmod(0o600)
        self.log.log("seed", f"wrote bootstrap {path}")

    def _write_systemd_unit(self) -> None:
        unit_path = self.rootfs / SEED_UNIT_PATH.lstrip("/")
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(_ELFIN_SERVICE_UNIT)
        unit_path.chmod(0o644)
        self.log.log("seed", f"wrote unit {unit_path}")

    def _enable_systemd_unit(self) -> None:
        # Manual symlink into multi-user.target.wants avoids a chroot dependency.
        wants_dir = self.rootfs / "etc/systemd/system/multi-user.target.wants"
        wants_dir.mkdir(parents=True, exist_ok=True)
        link = wants_dir / "elfin.service"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(SEED_UNIT_PATH)
        self.log.log("seed", f"enabled unit via {link}")

    def _place_bun_binary(self) -> None:
        # Placeholder: real implementation downloads bun-linux-aarch64 from the
        # pinned Bun release, verifies sha256, unzips into SEED_BUN_PATH.
        # Left for the Bun-pin follow-up PR; see BUN_VERSION/BUN_SHA256 pins.
        self.log.log("seed", "bun install: SKIPPED (pins not set)")


_ELFIN_SERVICE_UNIT = """\
[Unit]
Description=Elfin Survival Intelligence Companion
After=local-fs.target

[Service]
Type=simple
WorkingDirectory=/opt/elfin
ExecStart=/usr/local/bin/bun run /opt/elfin/src/backend/server.ts
Restart=on-failure
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
"""


# ---------------------------------------------------------------------------
# Disk selector
# ---------------------------------------------------------------------------


class DiskSelector:
    def __init__(self, log: StepLogger) -> None:
        self.log = log

    def interactive_pick(
        self, noninteractive_target: Optional[str] = None
    ) -> DiskCandidate:
        candidates = self._list()
        root_disk = find_root_disk(Path("/proc/mounts").read_text())
        self.log.log("select", f"host root disk: {root_disk}")

        if noninteractive_target:
            for c in candidates:
                if c.path == noninteractive_target:
                    err = validate_target_disk(c, root_disk)
                    if err:
                        raise SystemExit(f"target rejected: {err}")
                    return c
            raise SystemExit(f"target {noninteractive_target} not found")

        viable: list[DiskCandidate] = []
        for c in candidates:
            err = validate_target_disk(c, root_disk)
            if err:
                self.log.log("select", f"skip {c.path}: {err}")
                continue
            viable.append(c)

        if not viable:
            raise SystemExit("no viable target disks found")

        print("\nAvailable target disks:\n", file=sys.stderr)
        for i, c in enumerate(viable):
            print(
                f"  [{i}] {c.path}  {c.size_bytes // (1024**3)} GiB  "
                f"{c.model or '(no model)'}",
                file=sys.stderr,
            )
        choice = input("Select disk index: ").strip()
        if not choice.isdigit() or int(choice) not in range(len(viable)):
            raise SystemExit("invalid selection")
        picked = viable[int(choice)]
        confirm = input(
            f"\nWILL WRITE TO {picked.path} ({picked.size_bytes // (1024**3)} GiB, "
            f"{picked.model or 'no model'}). Type the device path to confirm: "
        ).strip()
        if confirm != picked.path:
            raise SystemExit("confirmation did not match; aborting")
        return picked

    def _list(self) -> list[DiskCandidate]:
        out = subprocess.check_output(
            ["lsblk", "-J", "-b", "-o", "NAME,SIZE,MODEL,TYPE,MOUNTPOINTS,PATH"],
            text=True,
        )
        return parse_lsblk_json(out)


# ---------------------------------------------------------------------------
# Disk flasher — invoke ubuntu-rockchip-install
# ---------------------------------------------------------------------------


class DiskFlasher:
    def __init__(self, log: StepLogger, cache_dir: Path) -> None:
        self.log = log
        self.cache_dir = cache_dir

    def flash(self, image_raw: Path, target: DiskCandidate) -> None:
        urock_dir = self._bootstrap_installer()
        installer = urock_dir / "ubuntu-rockchip-install"
        if not installer.exists():
            raise SystemExit(f"ubuntu-rockchip-install not found at {installer}")
        self.log.log("flash", f"writing {image_raw} to {target.path}")
        subprocess.run(
            [str(installer), "--image", str(image_raw), "--device", target.path],
            check=True,
        )
        subprocess.run(["sync"], check=True)
        self.log.log("flash", "flash complete")

    def _bootstrap_installer(self) -> Path:
        urock_dir = self.cache_dir / "ubuntu-rockchip"
        if not urock_dir.exists():
            self.log.log("flash", f"cloning {UROCK_REPO}")
            subprocess.run(
                ["git", "clone", UROCK_REPO, str(urock_dir)], check=True
            )
        if UROCK_COMMIT:
            subprocess.run(
                ["git", "-C", str(urock_dir), "fetch", "--all", "--tags"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(urock_dir), "checkout", UROCK_COMMIT],
                check=True,
            )
        return urock_dir


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    log_dir = Path(__file__).resolve().parent / ".logs"
    log_path = log_dir / f"prepare_image-{dt.datetime.now().strftime('%Y%m%dT%H%M%SZ')}.log"
    log = StepLogger(log_path)
    _install_signal_handlers()

    try:
        host_doctor(log, allow_unpinned=args.allow_unpinned)
        require_root()

        cache_dir = Path(args.cache_dir).expanduser().resolve()
        source_tree = Path(__file__).resolve().parents[1]
        log.log("setup", f"source tree: {source_tree}")
        log.log("setup", f"cache dir: {cache_dir}")

        fetcher = ImageFetcher(log, cache_dir)
        image_xz = fetcher.fetch()

        with tempfile.TemporaryDirectory(prefix="elfin-prep-") as td:
            workdir = Path(td)
            with LoopMount(log, image_xz, workdir) as mnt:
                assert mnt.root_mount is not None
                Seeder(log, mnt.root_mount, source_tree).run()
                image_raw = mnt.image_raw
                assert image_raw is not None
            # Loop/mounts released; image_raw still exists in workdir.

            selector = DiskSelector(log)
            target = selector.interactive_pick(args.target)

            if args.dry_run:
                log.log("dry-run", f"would flash {image_raw} to {target.path}")
                log.log("done", "DRY-RUN COMPLETE")
                return 0

            DiskFlasher(log, cache_dir).flash(image_raw, target)

        log.log("done", f"ELFIN IMAGE READY ON {target.path}")
        return 0
    except KeyboardInterrupt:
        log.log("interrupt", "interrupted by user")
        return 130
    except subprocess.CalledProcessError as e:
        log.log("error", f"subprocess failed: {' '.join(e.cmd)} (rc={e.returncode})")
        return 1
    except SystemExit as e:
        msg = str(e) if e.code not in (0, None) else ""
        if msg:
            log.log("error", msg)
        return int(e.code) if isinstance(e.code, int) else 1
    except Exception as e:
        log.log("error", f"unexpected: {type(e).__name__}: {e}")
        return 1
    finally:
        log.close()


def _parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="prepare_image.py",
        description="Prepare an Elfin-ready disk for Turing RK1 / RK3588.",
    )
    p.add_argument(
        "--cache-dir",
        default="~/.cache/elfin/prepare-image",
        help="Where downloaded images and the installer repo are cached.",
    )
    p.add_argument(
        "--target",
        default=None,
        help="Skip interactive prompt; use this block device (still safety-checked).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Run every step except the destructive flash.",
    )
    p.add_argument(
        "--allow-unpinned",
        action="store_true",
        help="Dev only: proceed even if upstream pins are not set.",
    )
    return p.parse_args(argv)


def _install_signal_handlers() -> None:
    def _raise_keyboard(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, _raise_keyboard)
    signal.signal(signal.SIGTERM, _raise_keyboard)


if __name__ == "__main__":
    sys.exit(main())
