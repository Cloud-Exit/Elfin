from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.prepare_image import (
    DiskCandidate,
    check_pins,
    check_tools_present,
    find_root_disk,
    parse_lsblk_json,
    validate_target_disk,
    verify_sha256,
    _strip_partition_suffix,
    MIN_TARGET_DISK_BYTES,
)


class LsblkParseTests(unittest.TestCase):
    def test_parses_disks_and_skips_partitions(self) -> None:
        payload = json.dumps(
            {
                "blockdevices": [
                    {
                        "name": "sda",
                        "path": "/dev/sda",
                        "size": 500_000_000_000,
                        "model": "Samsung SSD",
                        "type": "disk",
                        "mountpoints": [None],
                        "children": [
                            {
                                "name": "sda1",
                                "type": "part",
                                "mountpoints": ["/"],
                            }
                        ],
                    },
                    {
                        "name": "loop0",
                        "path": "/dev/loop0",
                        "size": 1024,
                        "type": "loop",
                        "mountpoints": [None],
                    },
                ]
            }
        )
        result = parse_lsblk_json(payload)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].path, "/dev/sda")
        self.assertEqual(result[0].size_bytes, 500_000_000_000)
        self.assertTrue(result[0].is_mounted())

    def test_rejects_invalid_json(self) -> None:
        with self.assertRaises(ValueError):
            parse_lsblk_json("not json")


class StripPartitionSuffixTests(unittest.TestCase):
    def test_sda1(self) -> None:
        self.assertEqual(_strip_partition_suffix("/dev/sda1"), "/dev/sda")

    def test_nvme(self) -> None:
        self.assertEqual(_strip_partition_suffix("/dev/nvme0n1p3"), "/dev/nvme0n1")

    def test_mmcblk(self) -> None:
        self.assertEqual(_strip_partition_suffix("/dev/mmcblk0p1"), "/dev/mmcblk0")

    def test_plain_device(self) -> None:
        self.assertEqual(_strip_partition_suffix("/dev/sda"), "/dev/sda")


class FindRootDiskTests(unittest.TestCase):
    def test_finds_root_and_strips_partition(self) -> None:
        mounts = (
            "/dev/sda1 / ext4 rw 0 0\n"
            "tmpfs /tmp tmpfs rw 0 0\n"
        )
        self.assertEqual(find_root_disk(mounts), "/dev/sda")

    def test_returns_none_when_no_root(self) -> None:
        self.assertIsNone(find_root_disk("tmpfs /tmp tmpfs rw 0 0\n"))


class ValidateTargetDiskTests(unittest.TestCase):
    def _disk(self, **kw) -> DiskCandidate:
        defaults = dict(
            name="sdb",
            path="/dev/sdb",
            size_bytes=MIN_TARGET_DISK_BYTES + 1,
            model="Kingston",
            mountpoints=(),
        )
        defaults.update(kw)
        return DiskCandidate(**defaults)

    def test_accepts_clean_big_disk(self) -> None:
        self.assertIsNone(validate_target_disk(self._disk(), "/dev/sda"))

    def test_rejects_root_disk(self) -> None:
        err = validate_target_disk(self._disk(path="/dev/sda"), "/dev/sda")
        self.assertIn("root disk", err or "")

    def test_rejects_mounted(self) -> None:
        err = validate_target_disk(
            self._disk(mountpoints=("/mnt/usb",)), "/dev/sda"
        )
        self.assertIn("mounted", err or "")

    def test_rejects_too_small(self) -> None:
        err = validate_target_disk(self._disk(size_bytes=1024), "/dev/sda")
        self.assertIn("too small", err or "")


class VerifySha256Tests(unittest.TestCase):
    def test_matches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "blob"
            p.write_bytes(b"hello world")
            digest = hashlib.sha256(b"hello world").hexdigest()
            self.assertTrue(verify_sha256(p, digest))

    def test_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "blob"
            p.write_bytes(b"hello world")
            self.assertFalse(verify_sha256(p, "0" * 64))


class CheckToolsPresentTests(unittest.TestCase):
    def test_reports_missing(self) -> None:
        missing = check_tools_present(["definitely-not-a-real-tool-xyz"])
        self.assertEqual(missing, ["definitely-not-a-real-tool-xyz"])

    def test_empty_when_all_present(self) -> None:
        # `sh` exists on any reasonable POSIX host.
        self.assertEqual(check_tools_present(["sh"]), [])


class CheckPinsTests(unittest.TestCase):
    def test_placeholders_flagged(self) -> None:
        # With default placeholder pins, all four should be reported.
        missing = check_pins(allow_unpinned=True)
        self.assertIn("IMAGE_SHA256", missing)
        self.assertIn("UROCK_COMMIT", missing)
        self.assertIn("BUN_VERSION", missing)
        self.assertIn("BUN_SHA256", missing)


if __name__ == "__main__":
    unittest.main()
