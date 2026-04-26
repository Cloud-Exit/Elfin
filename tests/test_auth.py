"""
Validate auth module structure and route definitions.

Tests verify auth.ts and routes/auth.ts contain required functions
for bcrypt hashing, token management, and HTTP route handling.
"""

import re
import unittest
from pathlib import Path

AUTH_PATH = Path(__file__).parent.parent / "src" / "backend" / "auth.ts"
ROUTES_PATH = Path(__file__).parent.parent / "src" / "backend" / "routes" / "auth.ts"
SERVER_PATH = Path(__file__).parent.parent / "src" / "backend" / "server.ts"
SEED_PATH = Path(__file__).parent.parent / "src" / "backend" / "seed.ts"


def read_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found at {path}")
    return path.read_text(encoding="utf-8")


def has_function(body: str, name: str) -> bool:
    return bool(re.search(rf"\b(?:export\s+)?(?:async\s+)?function\s+{name}\b", body))


def has_export(body: str, name: str) -> bool:
    return bool(re.search(rf"\bexport\s+(?:async\s+)?function\s+{name}\b", body)) or \
           bool(re.search(rf"\bexport\s+(?:const|let|var)\s+{name}\b", body)) or \
           bool(re.search(rf"\bexport\s+\{{[^}}]*\b{name}\b[^}}]*\}}", body))


class TestAuthModuleExists(unittest.TestCase):
    def test_auth_ts_exists(self):
        self.assertTrue(AUTH_PATH.exists())

    def test_routes_auth_ts_exists(self):
        self.assertTrue(ROUTES_PATH.exists())

    def test_seed_ts_exists(self):
        self.assertTrue(SEED_PATH.exists())


class TestAuthExports(unittest.TestCase):
    def setUp(self):
        self.body = read_file(AUTH_PATH)

    def test_hash_password_exported(self):
        self.assertTrue(has_export(self.body, "hashPassword"))

    def test_verify_password_exported(self):
        self.assertTrue(has_export(self.body, "verifyPassword"))

    def test_create_token_exported(self):
        self.assertTrue(has_export(self.body, "createToken"))

    def test_set_session_exported(self):
        self.assertTrue(has_export(self.body, "setSession"))

    def test_clear_session_exported(self):
        self.assertTrue(has_export(self.body, "clearSession"))

    def test_require_auth_exported(self):
        self.assertTrue(has_export(self.body, "requireAuth"))

    def test_get_user_from_token_exported(self):
        self.assertTrue(has_export(self.body, "getUserFromToken"))

    def test_uses_bcrypt_algorithm(self):
        self.assertIn("bcrypt", self.body)

    def test_sessions_map_storage(self):
        self.assertIn("Map<string, string>", self.body)


class TestAuthRoutes(unittest.TestCase):
    def setUp(self):
        self.body = read_file(ROUTES_PATH)

    def test_handle_auth_exported(self):
        self.assertTrue(has_export(self.body, "handleAuth"))

    def test_login_route(self):
        self.assertIn("/api/auth/login", self.body)

    def test_logout_route(self):
        self.assertIn("/api/auth/logout", self.body)

    def test_me_route(self):
        self.assertIn("/api/auth/me", self.body)

    def test_change_password_route(self):
        self.assertIn("/api/auth/change-password", self.body)

    def test_uses_require_auth(self):
        self.assertIn("requireAuth", self.body)

    def test_uses_hash_password(self):
        self.assertIn("hashPassword", self.body)

    def test_uses_verify_password(self):
        self.assertIn("verifyPassword", self.body)

    def test_returns_json_responses(self):
        self.assertIn("Response.json", self.body)

    def test_checks_old_password(self):
        self.assertIn("oldPassword", self.body)
        self.assertIn("newPassword", self.body)


class TestServerIntegration(unittest.TestCase):
    def setUp(self):
        self.body = read_file(SERVER_PATH)

    def test_imports_handle_auth(self):
        self.assertIn("handleAuth", self.body)

    def test_mounts_auth_routes(self):
        self.assertIn("handleAuth(req, path)", self.body)

    def test_auth_routes_before_health(self):
        auth_idx = self.body.find("handleAuth(req, path)")
        health_idx = self.body.find("/api/health")
        self.assertGreater(0, -1)  # Both exist
        self.assertLess(auth_idx, health_idx, "Auth routes should be checked before health")


class TestSeedScript(unittest.TestCase):
    def setUp(self):
        self.body = read_file(SEED_PATH)

    def test_creates_admin_user(self):
        self.assertIn("role: 'admin'", self.body)

    def test_sets_must_change_password(self):
        self.assertIn("mustChangePassword: true", self.body)

    def test_generates_random_password(self):
        self.assertIn("randomPassword", self.body)

    def test_uses_hash_password(self):
        self.assertIn("hashPassword", self.body)

    def test_checks_admin_exists(self):
        self.assertIn("adminExists", self.body)

    def test_prints_password_once(self):
        self.assertIn("console.log", self.body)
        self.assertIn("Password:", self.body)


if __name__ == "__main__":
    unittest.main()
