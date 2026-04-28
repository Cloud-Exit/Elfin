"""
Validate baseline interview route structure.

Tests verify routes/baseline.ts contains required handlers,
auth guards, baseline categories, and schema validation.
"""

import re
import unittest
from pathlib import Path

BASELINE_PATH = Path(__file__).parent.parent / "src" / "backend" / "routes" / "baseline.ts"
SERVER_PATH = Path(__file__).parent.parent / "src" / "backend" / "server.ts"
SCHEMAS_PATH = Path(__file__).parent.parent / "src" / "backend" / "utils" / "schemas.ts"


def read_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found at {path}")
    return path.read_text(encoding="utf-8")


def has_function(body: str, name: str) -> bool:
    return bool(re.search(rf"\b(?:export\s+)?(?:async\s+)?function\s+{name}\b", body))


class TestBaselineRouteExists(unittest.TestCase):
    def test_baseline_ts_exists(self):
        self.assertTrue(BASELINE_PATH.exists())


class TestBaselineRoute(unittest.TestCase):
    def setUp(self):
        self.body = read_file(BASELINE_PATH)

    def test_handle_baseline_exported(self):
        self.assertTrue(has_function(self.body, "handleBaseline"))

    def test_get_baseline_function(self):
        self.assertTrue(has_function(self.body, "getBaseline"))

    def test_submit_baseline_function(self):
        self.assertTrue(has_function(self.body, "submitBaseline"))

    def test_reset_baseline_function(self):
        self.assertTrue(has_function(self.body, "resetBaseline"))

    def test_uses_require_auth(self):
        self.assertIn("requireAuth", self.body)

    def test_uses_prisma_user(self):
        self.assertIn("prisma.user", self.body)

    def test_baseline_categories(self):
        """Baseline must cover all required health categories."""
        for category in ['conditions', 'meds', 'allergies', 'fitness', 'mentalHealth', 'vision', 'chronicPain', 'diet']:
            self.assertIn(category, self.body)

    def test_parse_baseline_exists(self):
        """Baseline JSON string must be parsed into structured data."""
        self.assertIn("parseBaseline", self.body)
        self.assertIn("JSON.parse", self.body)

    def test_json_stringify(self):
        """Baseline must be stored as JSON string."""
        self.assertIn("JSON.stringify", self.body)

    def test_completion_detection(self):
        """Baseline completion must be tracked."""
        self.assertIn("completed", self.body)

    def test_needs_baseline_flag(self):
        """NeedsBaseline flag must be returned to indicate interview status."""
        self.assertIn("needsBaseline", self.body)

    def test_returns_404_on_not_found(self):
        self.assertIn("404", self.body)

    def test_user_id_isolation(self):
        self.assertIn("ctx.userId", self.body)

    def test_baseline_route_prefix(self):
        self.assertIn("'baseline'", self.body)

    def test_checks_parts_1_not_parts_0(self):
        """Route must check parts[1] for 'baseline', not parts[0], because path includes /api prefix."""
        self.assertIn("parts[1] !== 'baseline'", self.body)
        self.assertNotIn("parts[0] !== 'baseline'", self.body)

    def test_uses_zod_schemas(self):
        """Baseline route must use Zod schemas for validation."""
        self.assertIn("baselineSubmitSchema", self.body)
        self.assertIn("baselineSchema", self.body)

    def test_safe_parse_validation(self):
        """Baseline route must use safeParse for validation."""
        self.assertIn("safeParse", self.body)

    def test_build_interview_state(self):
        """Route must build interview state with progress tracking."""
        self.assertIn("buildInterviewState", self.body)

    def test_next_category_tracking(self):
        """Interview state must track next unanswered category."""
        self.assertIn("nextCategory", self.body)

    def test_interview_in_response(self):
        """GET and POST responses must include interview state."""
        self.assertIn("interview", self.body)

    def test_baseline_questions_imported(self):
        """Route must import baselineQuestions for prompts."""
        self.assertIn("baselineQuestions", self.body)

    def test_answered_count(self):
        """Interview state must track answered category count."""
        self.assertIn("answered", self.body)


class TestBaselineSchemas(unittest.TestCase):
    def setUp(self):
        self.body = read_file(SCHEMAS_PATH)

    def test_baseline_categories_defined(self):
        """baselineCategories array must be defined in schemas."""
        self.assertIn("baselineCategories", self.body)

    def test_baseline_questions_defined(self):
        """baselineQuestions map must be defined for interview prompts."""
        self.assertIn("baselineQuestions", self.body)

    def test_baseline_schema_defined(self):
        """baselineSchema must be defined in schemas."""
        self.assertIn("baselineSchema", self.body)

    def test_baseline_schema_refine(self):
        """baselineSchema must have .refine() to reject empty submissions."""
        # Find baselineSchema definition and check it has .refine
        idx = self.body.find("baselineSchema")
        chunk = self.body[idx:idx + 500]
        self.assertIn(".refine", chunk, "baselineSchema must use .refine to require at least one field")

    def test_baseline_submit_schema_defined(self):
        """baselineSubmitSchema must be defined in schemas."""
        self.assertIn("baselineSubmitSchema", self.body)

    def test_category_enum(self):
        """baselineSubmitSchema must use enum for category validation."""
        self.assertIn("z.enum", self.body)

    def test_response_trim_min(self):
        """baselineSubmitSchema response must be trimmed and non-empty."""
        self.assertIn(".trim()", self.body)
        self.assertIn(".min(1)", self.body)


class TestServerIntegration(unittest.TestCase):
    def setUp(self):
        self.body = read_file(SERVER_PATH)

    def test_imports_handle_baseline(self):
        self.assertIn("handleBaseline", self.body)

    def test_mounts_baseline_routes(self):
        self.assertIn("handleBaseline(req, path)", self.body)

    def test_routes_after_auth(self):
        auth_idx = self.body.find("handleAuth(req, path)")
        baseline_idx = self.body.find("handleBaseline(req, path)")
        self.assertGreater(baseline_idx, auth_idx, "Baseline routes should be after auth")


if __name__ == "__main__":
    unittest.main()
