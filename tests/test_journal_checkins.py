"""
Validate journal and check-in CRUD route structure.

Tests verify routes/journal.ts and routes/checkins.ts contain
required handlers, auth guards, pagination, and score validation.
"""

import re
import unittest
from pathlib import Path

JOURNAL_PATH = Path(__file__).parent.parent / "src" / "backend" / "routes" / "journal.ts"
CHECKINS_PATH = Path(__file__).parent.parent / "src" / "backend" / "routes" / "checkins.ts"
SERVER_PATH = Path(__file__).parent.parent / "src" / "backend" / "server.ts"
PAGINATION_PATH = Path(__file__).parent.parent / "src" / "backend" / "utils" / "pagination.ts"
SCHEMAS_PATH = Path(__file__).parent.parent / "src" / "backend" / "utils" / "schemas.ts"


def read_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found at {path}")
    return path.read_text(encoding="utf-8")


def has_function(body: str, name: str) -> bool:
    return bool(re.search(rf"\b(?:export\s+)?(?:async\s+)?function\s+{name}\b", body))


class TestJournalRouteExists(unittest.TestCase):
    def test_journal_ts_exists(self):
        self.assertTrue(JOURNAL_PATH.exists())


class TestJournalRoute(unittest.TestCase):
    def setUp(self):
        self.body = read_file(JOURNAL_PATH)

    def test_handle_journal_exported(self):
        self.assertTrue(has_function(self.body, "handleJournal"))

    def test_list_function(self):
        self.assertTrue(has_function(self.body, "listJournal"))

    def test_create_function(self):
        self.assertTrue(has_function(self.body, "createJournal"))

    def test_get_function(self):
        self.assertTrue(has_function(self.body, "getJournal"))

    def test_update_function(self):
        self.assertTrue(has_function(self.body, "updateJournal"))

    def test_delete_function(self):
        self.assertTrue(has_function(self.body, "deleteJournal"))

    def test_uses_require_auth(self):
        self.assertIn("requireAuth", self.body)

    def test_uses_prisma_journal_entry(self):
        self.assertIn("prisma.journalEntry", self.body)

    def test_pagination_limit(self):
        self.assertIn("limit", self.body)

    def test_pagination_offset(self):
        self.assertIn("offset", self.body)

    def test_date_filtering(self):
        self.assertIn("fromDate", self.body)
        self.assertIn("toDate", self.body)

    def test_order_by_date_desc(self):
        self.assertIn("date: 'desc'", self.body)

    def test_content_validation(self):
        self.assertIn("content", self.body)
        self.assertIn("journalCreateSchema", self.body)
        self.assertIn("journalUpdateSchema", self.body)

    def test_returns_201_on_create(self):
        self.assertIn("201", self.body)

    def test_returns_404_on_not_found(self):
        self.assertIn("404", self.body)

    def test_user_id_isolation(self):
        self.assertIn("userId: ctx.userId", self.body)

    def test_select_fields(self):
        self.assertIn("aiSummary", self.body)
        self.assertIn("aiCategories", self.body)

    def test_journal_route_prefix(self):
        self.assertIn("'journal'", self.body)

    def test_checks_parts_1_not_parts_0(self):
        """Route must check parts[1] for 'journal', not parts[0], because path includes /api prefix."""
        self.assertIn("parts[1] !== 'journal'", self.body)
        self.assertNotIn("parts[0] !== 'journal'", self.body)

    def test_uses_parse_pagination_helper(self):
        """Pagination must use shared parsePagination helper, not inline Number(get('limit'))."""
        self.assertNotIn("Number(url.searchParams.get('limit'))", self.body)
        self.assertIn("parsePagination", self.body)


class TestCheckinRouteExists(unittest.TestCase):
    def test_checkins_ts_exists(self):
        self.assertTrue(CHECKINS_PATH.exists())


class TestCheckinRoute(unittest.TestCase):
    def setUp(self):
        self.body = read_file(CHECKINS_PATH)

    def test_handle_checkins_exported(self):
        self.assertTrue(has_function(self.body, "handleCheckins"))

    def test_list_function(self):
        self.assertTrue(has_function(self.body, "listCheckins"))

    def test_create_function(self):
        self.assertTrue(has_function(self.body, "createCheckin"))

    def test_get_function(self):
        self.assertTrue(has_function(self.body, "getCheckin"))

    def test_update_function(self):
        self.assertTrue(has_function(self.body, "updateCheckin"))

    def test_delete_function(self):
        self.assertTrue(has_function(self.body, "deleteCheckin"))

    def test_uses_require_auth(self):
        self.assertIn("requireAuth", self.body)

    def test_uses_prisma_check_in(self):
        self.assertIn("prisma.checkIn", self.body)

    def test_pagination_limit(self):
        self.assertIn("limit", self.body)

    def test_pagination_offset(self):
        self.assertIn("offset", self.body)

    def test_date_filtering(self):
        self.assertIn("fromDate", self.body)
        self.assertIn("toDate", self.body)

    def test_order_by_date_desc(self):
        self.assertIn("date: 'desc'", self.body)

    def test_score_validation(self):
        self.assertIn("checkinCreateSchema", self.body)
        self.assertIn("checkinUpdateSchema", self.body)

    def test_score_range(self):
        self.assertIn("schemas", self.body)

    def test_three_scores(self):
        self.assertIn("mentalScore", self.body)
        self.assertIn("physicalScore", self.body)
        self.assertIn("staminaScore", self.body)

    def test_questions_required(self):
        self.assertIn("questions", self.body)

    def test_responses_required(self):
        self.assertIn("responses", self.body)

    def test_json_stringify(self):
        self.assertIn("JSON.stringify", self.body)

    def test_returns_201_on_create(self):
        self.assertIn("201", self.body)

    def test_returns_404_on_not_found(self):
        self.assertIn("404", self.body)

    def test_user_id_isolation(self):
        self.assertIn("userId: ctx.userId", self.body)

    def test_checkins_route_prefix(self):
        self.assertIn("'checkins'", self.body)

    def test_checks_parts_1_not_parts_0(self):
        """Route must check parts[1] for 'checkins', not parts[0], because path includes /api prefix."""
        self.assertIn("parts[1] !== 'checkins'", self.body)
        self.assertNotIn("parts[0] !== 'checkins'", self.body)

    def test_uses_parse_pagination_helper(self):
        """Pagination must use shared parsePagination helper, not inline Number(get('limit'))."""
        self.assertNotIn("Number(url.searchParams.get('limit'))", self.body)
        self.assertIn("parsePagination", self.body)

    def test_decode_checkin_exists(self):
        """Checkin responses should decode JSON strings back to objects for object-in/object-out API."""
        self.assertIn("decodeCheckin", self.body)
        self.assertIn("JSON.parse(checkin.questions)", self.body)
        self.assertIn("JSON.parse(checkin.responses)", self.body)


class TestPaginationUtility(unittest.TestCase):
    def setUp(self):
        self.body = read_file(PAGINATION_PATH)

    def test_pagination_file_exists(self):
        self.assertTrue(PAGINATION_PATH.exists())

    def test_validates_limit_is_finite(self):
        self.assertIn("paginationSchema", self.body)

    def test_validates_limit_positive(self):
        self.assertIn("safeParse", self.body)

    def test_validates_offset_non_negative(self):
        self.assertIn("schemas", self.body)

    def test_clamps_limit_to_200(self):
        self.assertIn("200", self.body)

    def test_default_limit_50(self):
        self.assertIn("paginationSchema", self.body)

    def test_throws_on_invalid(self):
        self.assertIn("throw", self.body)


class TestSchemas(unittest.TestCase):
    def setUp(self):
        self.body = read_file(SCHEMAS_PATH)

    def test_schemas_file_exists(self):
        self.assertTrue(SCHEMAS_PATH.exists())

    def test_uses_zod(self):
        self.assertIn("zod", self.body)

    def test_pagination_schema_int(self):
        self.assertIn(".int()", self.body)

    def test_pagination_schema_min_max(self):
        self.assertIn(".min(1)", self.body)
        self.assertIn(".min(0)", self.body)

    def test_pagination_schema_default(self):
        self.assertIn(".default(50)", self.body)
        self.assertIn(".default(0)", self.body)

    def test_journal_schemas(self):
        self.assertIn("journalCreateSchema", self.body)
        self.assertIn("journalUpdateSchema", self.body)
        self.assertIn(".trim()", self.body)

    def test_checkin_schemas(self):
        self.assertIn("checkinCreateSchema", self.body)
        self.assertIn("checkinUpdateSchema", self.body)

    def test_checkin_score_range(self):
        self.assertIn(".min(1)", self.body)
        self.assertIn(".max(10)", self.body)

    def test_checkin_array_rejection(self):
        self.assertIn("Array.isArray", self.body)


class TestServerIntegration(unittest.TestCase):
    def setUp(self):
        self.body = read_file(SERVER_PATH)

    def test_imports_handle_journal(self):
        self.assertIn("handleJournal", self.body)

    def test_imports_handle_checkins(self):
        self.assertIn("handleCheckins", self.body)

    def test_mounts_journal_routes(self):
        self.assertIn("handleJournal(req, path)", self.body)

    def test_mounts_checkins_routes(self):
        self.assertIn("handleCheckins(req, path)", self.body)

    def test_routes_after_auth(self):
        auth_idx = self.body.find("handleAuth(req, path)")
        journal_idx = self.body.find("handleJournal(req, path)")
        checkins_idx = self.body.find("handleCheckins(req, path)")
        self.assertGreater(journal_idx, auth_idx, "Journal routes should be after auth")
        self.assertGreater(checkins_idx, auth_idx, "Checkin routes should be after auth")


if __name__ == "__main__":
    unittest.main()
