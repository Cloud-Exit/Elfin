"""
Validate check-in AI prompt and response endpoints.

Tests verify checkinService.ts, new route handlers, scoring logic,
and schema validation for check-in responses.
"""

import re
import unittest
from pathlib import Path

CHECKINS_PATH = Path(__file__).parent.parent / "src" / "backend" / "routes" / "checkins.ts"
CHECKIN_SERVICE_PATH = Path(__file__).parent.parent / "src" / "backend" / "checkinService.ts"
SCHEMAS_PATH = Path(__file__).parent.parent / "src" / "backend" / "utils" / "schemas.ts"
SERVER_PATH = Path(__file__).parent.parent / "src" / "backend" / "server.ts"


def read_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found at {path}")
    return path.read_text(encoding="utf-8")


def has_function(body: str, name: str) -> bool:
    return bool(re.search(rf"\b(?:export\s+)?(?:async\s+)?function\s+{name}\b", body))


class TestCheckinServiceExists(unittest.TestCase):
    def test_checkin_service_ts_exists(self):
        self.assertTrue(CHECKIN_SERVICE_PATH.exists())


class TestCheckinService(unittest.TestCase):
    def setUp(self):
        self.body = read_file(CHECKIN_SERVICE_PATH)

    def test_gather_checkin_context_function(self):
        self.assertTrue(has_function(self.body, "gatherCheckinContext"))

    def test_generate_checkin_questions_function(self):
        self.assertTrue(has_function(self.body, "generateCheckinQuestions"))

    def test_score_responses_function(self):
        self.assertTrue(has_function(self.body, "scoreResponses"))

    def test_uses_prisma_user(self):
        self.assertIn("prisma.user", self.body)

    def test_uses_prisma_journal(self):
        self.assertIn("prisma.journalEntry", self.body)

    def test_uses_prisma_checkin(self):
        self.assertIn("prisma.checkIn", self.body)

    def test_scores_mental_dimension(self):
        self.assertIn("mental", self.body)

    def test_scores_physical_dimension(self):
        self.assertIn("physical", self.body)

    def test_scores_stamina_dimension(self):
        self.assertIn("stamina", self.body)

    def test_score_range_1_to_10(self):
        self.assertIn("Math.max(1", self.body)
        self.assertIn("Math.min(10", self.body)

    def test_baseline_context_used(self):
        self.assertIn("baseline", self.body)

    def test_journal_context_used(self):
        self.assertIn("journal", self.body.lower())

    def test_recent_journal_entries_fetched(self):
        self.assertIn("recentJournal", self.body)

    def test_last_checkin_context_used(self):
        self.assertIn("lastCheckin", self.body)

    def test_baseline_conditions_question(self):
        self.assertIn("conditions", self.body)

    def test_baseline_chronicPain_question(self):
        self.assertIn("chronicPain", self.body)

    def test_baseline_mentalHealth_question(self):
        self.assertIn("mentalHealth", self.body)


class TestCheckinRoute(unittest.TestCase):
    def setUp(self):
        self.body = read_file(CHECKINS_PATH)

    def test_prompt_endpoint_exists(self):
        self.assertIn("prompt", self.body)

    def test_respond_endpoint_exists(self):
        self.assertIn("respond", self.body)

    def test_skip_endpoint_exists(self):
        self.assertIn("skip", self.body)

    def test_uses_checkin_service(self):
        self.assertIn("checkinService", self.body)

    def test_imports_gather_checkin_context(self):
        self.assertIn("gatherCheckinContext", self.body)

    def test_uses_service_generate_questions(self):
        self.assertIn("checkinService.generateQuestions", self.body)

    def test_uses_service_score_responses(self):
        self.assertIn("checkinService.scoreResponses", self.body)

    def test_prompt_returns_questions(self):
        self.assertIn("questions", self.body)

    def test_respond_returns_scores(self):
        self.assertIn("scores", self.body)

    def test_promptId_not_found_returns_404(self):
        """Missing promptId must return 404, not silently fall back."""
        self.assertIn("promptId not found", self.body)

    def test_skip_returns_skipped_flag(self):
        self.assertIn("skipped", self.body)

    def test_uses_require_auth(self):
        self.assertIn("requireAuth", self.body)

    def test_uses_prisma_checkin(self):
        self.assertIn("prisma.checkIn", self.body)

    def test_prompt_route_registered(self):
        self.assertIn("parts[2] === 'prompt'", self.body)

    def test_respond_route_registered(self):
        self.assertIn("parts[2] === 'respond'", self.body)

    def test_skip_route_registered(self):
        self.assertIn("parts[2] === 'skip'", self.body)


class TestCheckinSchemas(unittest.TestCase):
    def setUp(self):
        self.body = read_file(SCHEMAS_PATH)

    def test_checkin_respond_schema_defined(self):
        self.assertIn("checkinRespondSchema", self.body)

    def test_checkin_prompt_schema_removed(self):
        """checkinPromptSchema was unused, should be removed."""
        self.assertNotIn("checkinPromptSchema", self.body)

    def test_respond_schema_has_questions(self):
        self.assertIn("questions: z.record", self.body)

    def test_respond_schema_has_responses(self):
        self.assertIn("responses: z.record", self.body)

    def test_respond_schema_has_skipped(self):
        self.assertIn("skipped: z.boolean", self.body)

    def test_respond_schema_refine(self):
        idx = self.body.find("checkinRespondSchema")
        chunk = self.body[idx:idx + 500]
        self.assertIn(".refine", chunk, "checkinRespondSchema must use .refine")


class TestCheckinServiceAI(unittest.TestCase):
    def setUp(self):
        self.body = read_file(CHECKIN_SERVICE_PATH)

    def test_ai_checkin_service_interface(self):
        """AI service boundary must be defined as interface."""
        self.assertIn("interface AICheckinService", self.body)

    def test_deterministic_fallback(self):
        """Deterministic fallback implementation must exist."""
        self.assertIn("DeterministicCheckinService", self.body)

    def test_llama_service_class(self):
        """Llama-server AI service class must exist for future integration."""
        self.assertIn("LlamaCheckinService", self.body)

    def test_inference_endpoint_config(self):
        """Llama service must accept inference endpoint configuration."""
        self.assertIn("inferenceEndpoint", self.body)

    def test_prompt_construction(self):
        """AI service must construct prompts from context."""
        self.assertIn("buildCheckinPrompt", self.body)

    def test_scoring_prompt_construction(self):
        """AI service must construct scoring prompts."""
        self.assertIn("buildScoringPrompt", self.body)

    def test_llama_api_call(self):
        """AI service must call llama-server /v1/chat/completions."""
        self.assertIn("/v1/chat/completions", self.body)

    def test_fallback_on_failure(self):
        """AI service must fall back to deterministic on failure."""
        self.assertIn("this.fallback", self.body)

    def test_exported_checkin_service(self):
        """checkinService must be exported for route injection."""
        self.assertIn("export let checkinService", self.body)

    def test_set_checkin_service(self):
        """setCheckinService must be exported for runtime swapping."""
        self.assertIn("setCheckinService", self.body)

    def test_journal_topics_extraction(self):
        """Journal content must be extracted for contextual questions."""
        self.assertIn("extractJournalTopics", self.body)

    def test_journal_followup_questions(self):
        """Journal follow-up questions must reference actual content."""
        self.assertIn("journalFollowup", self.body)

    def test_health_keywords_filtering(self):
        """Journal extraction must filter for health-relevant content."""
        self.assertIn("healthKeywords", self.body)

    def test_journal_time_reference(self):
        """Journal follow-up questions must include time reference."""
        self.assertIn("timeRef", self.body)


class TestServerIntegration(unittest.TestCase):
    def setUp(self):
        self.body = read_file(SERVER_PATH)

    def test_imports_handle_checkins(self):
        self.assertIn("handleCheckins", self.body)

    def test_mounts_checkins_routes(self):
        self.assertIn("handleCheckins(req, path)", self.body)

    def test_imports_set_checkin_service(self):
        """Server must import setCheckinService for AI initialization."""
        self.assertIn("setCheckinService", self.body)

    def test_imports_llama_checkin_service(self):
        """Server must import LlamaCheckinService for AI initialization."""
        self.assertIn("LlamaCheckinService", self.body)

    def test_imports_deterministic_checkin_service(self):
        """Server must import DeterministicCheckinService as fallback."""
        self.assertIn("DeterministicCheckinService", self.body)

    def test_configures_inference_endpoint(self):
        """Server must check ELFIN_INFERENCE_ENDPOINT env var."""
        self.assertIn("ELFIN_INFERENCE_ENDPOINT", self.body)

    def test_initializes_ai_service(self):
        """Server must call setCheckinService with LlamaCheckinService when endpoint configured."""
        self.assertIn("new LlamaCheckinService(", self.body)


if __name__ == "__main__":
    unittest.main()
