"""
Validate Prisma schema structure and model definitions.

These tests verify the schema.prisma file contains all required models,
fields, relations, and indexes without needing the Prisma CLI or engine.
"""

import re
import unittest
from pathlib import Path


SCHEMA_PATH = Path(__file__).parent.parent / "prisma" / "schema.prisma"


def read_schema() -> str:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema not found at {SCHEMA_PATH}")
    return SCHEMA_PATH.read_text(encoding="utf-8")


def extract_model(schema: str, model_name: str) -> str:
    """Extract the body of a model definition from the schema."""
    pattern = rf"model\s+{model_name}\s+\{{([^}}]+)\}}"
    match = re.search(pattern, schema, re.DOTALL)
    if not match:
        raise ValueError(f"Model '{model_name}' not found in schema")
    return match.group(1)


def has_field(model_body: str, field_name: str) -> bool:
    """Check if a model contains a field definition."""
    lines = model_body.strip().split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("@@"):
            continue
        tokens = stripped.split()
        if tokens and tokens[0] == field_name:
            return True
    return False


def has_index(model_body: str, index_fields: list[str]) -> bool:
    """Check if a model has an index on the given fields."""
    index_pattern = r"@@index\(\[([^\]]+)\]\)"
    for match in re.finditer(index_pattern, model_body):
        fields = [f.strip() for f in match.group(1).split(",")]
        if fields == index_fields:
            return True
    return False


def has_relation(model_body: str, relation_name: str) -> bool:
    """Check if a model has a relation field."""
    return has_field(model_body, relation_name)


class TestSchemaExists(unittest.TestCase):
    def test_schema_file_exists(self):
        self.assertTrue(SCHEMA_PATH.exists(), f"Schema file should exist at {SCHEMA_PATH}")


class TestGeneratorAndDatasource(unittest.TestCase):
    def setUp(self):
        self.schema = read_schema()

    def test_generator_client(self):
        self.assertIn('provider = "prisma-client-js"', self.schema)

    def test_datasource_sqlite(self):
        self.assertIn('provider = "sqlite"', self.schema)
        self.assertIn('url      = env("DATABASE_URL")', self.schema)


class TestUserModel(unittest.TestCase):
    def setUp(self):
        self.schema = read_schema()
        self.body = extract_model(self.schema, "User")

    def test_id_field(self):
        self.assertTrue(has_field(self.body, "id"))

    def test_username_field(self):
        self.assertTrue(has_field(self.body, "username"))

    def test_password_hash_field(self):
        self.assertTrue(has_field(self.body, "passwordHash"))

    def test_role_field(self):
        self.assertTrue(has_field(self.body, "role"))

    def test_must_change_password_field(self):
        self.assertTrue(has_field(self.body, "mustChangePassword"))

    def test_baseline_field(self):
        self.assertTrue(has_field(self.body, "baseline"))

    def test_created_at_field(self):
        self.assertTrue(has_field(self.body, "createdAt"))

    def test_unique_username(self):
        self.assertIn("@unique", self.body)

    def test_relations(self):
        self.assertTrue(has_relation(self.body, "journalEntries"))
        self.assertTrue(has_relation(self.body, "checkIns"))
        self.assertTrue(has_relation(self.body, "notes"))
        self.assertTrue(has_relation(self.body, "photos"))
        self.assertTrue(has_relation(self.body, "chatMessages"))


class TestJournalEntryModel(unittest.TestCase):
    def setUp(self):
        self.schema = read_schema()
        self.body = extract_model(self.schema, "JournalEntry")

    def test_required_fields(self):
        required = ["id", "userId", "user", "content", "date", "createdAt"]
        for field in required:
            self.assertTrue(has_field(self.body, field), f"Missing field: {field}")

    def test_optional_fields(self):
        optional = ["aiSummary", "aiCategories"]
        for field in optional:
            self.assertTrue(has_field(self.body, field), f"Missing optional field: {field}")

    def test_user_relation(self):
        self.assertTrue(has_relation(self.body, "user"))
        self.assertIn("onDelete: Cascade", self.body)

    def test_index_on_user_date(self):
        self.assertTrue(has_index(self.body, ["userId", "date"]))


class TestCheckInModel(unittest.TestCase):
    def setUp(self):
        self.schema = read_schema()
        self.body = extract_model(self.schema, "CheckIn")

    def test_required_fields(self):
        required = ["id", "userId", "user", "date", "questions", "responses", "createdAt"]
        for field in required:
            self.assertTrue(has_field(self.body, field), f"Missing field: {field}")

    def test_score_fields(self):
        scores = ["mentalScore", "physicalScore", "staminaScore"]
        for field in scores:
            self.assertTrue(has_field(self.body, field), f"Missing score field: {field}")

    def test_user_relation(self):
        self.assertTrue(has_relation(self.body, "user"))
        self.assertIn("onDelete: Cascade", self.body)

    def test_index_on_user_date(self):
        self.assertTrue(has_index(self.body, ["userId", "date"]))


class TestNoteModel(unittest.TestCase):
    def setUp(self):
        self.schema = read_schema()
        self.body = extract_model(self.schema, "Note")

    def test_required_fields(self):
        required = ["id", "userId", "user", "title", "content", "updatedAt", "createdAt"]
        for field in required:
            self.assertTrue(has_field(self.body, field), f"Missing field: {field}")

    def test_user_relation(self):
        self.assertTrue(has_relation(self.body, "user"))
        self.assertIn("onDelete: Cascade", self.body)

    def test_index_on_user_updated_at(self):
        self.assertTrue(has_index(self.body, ["userId", "updatedAt"]))


class TestPhotoModel(unittest.TestCase):
    def setUp(self):
        self.schema = read_schema()
        self.body = extract_model(self.schema, "Photo")

    def test_required_fields(self):
        required = ["id", "userId", "user", "filename", "path", "createdAt"]
        for field in required:
            self.assertTrue(has_field(self.body, field), f"Missing field: {field}")

    def test_optional_fields(self):
        optional = ["caption", "takenAt"]
        for field in optional:
            self.assertTrue(has_field(self.body, field), f"Missing optional field: {field}")

    def test_user_relation(self):
        self.assertTrue(has_relation(self.body, "user"))
        self.assertIn("onDelete: Cascade", self.body)

    def test_index_on_user_created_at(self):
        self.assertTrue(has_index(self.body, ["userId", "createdAt"]))


class TestChatMessageModel(unittest.TestCase):
    def setUp(self):
        self.schema = read_schema()
        self.body = extract_model(self.schema, "ChatMessage")

    def test_required_fields(self):
        required = ["id", "userId", "user", "role", "content", "createdAt"]
        for field in required:
            self.assertTrue(has_field(self.body, field), f"Missing field: {field}")

    def test_optional_fields(self):
        optional = ["sources", "images"]
        for field in optional:
            self.assertTrue(has_field(self.body, field), f"Missing optional field: {field}")

    def test_user_relation(self):
        self.assertTrue(has_relation(self.body, "user"))
        self.assertIn("onDelete: Cascade", self.body)

    def test_index_on_user_created_at(self):
        self.assertTrue(has_index(self.body, ["userId", "createdAt"]))


class TestSchemaCompleteness(unittest.TestCase):
    def setUp(self):
        self.schema = read_schema()

    def test_all_models_present(self):
        expected_models = ["User", "JournalEntry", "CheckIn", "Note", "Photo", "ChatMessage"]
        for model_name in expected_models:
            with self.subTest(model=model_name):
                extract_model(self.schema, model_name)

    def test_no_unknown_models(self):
        """Optional: ensure we don't have extra models we didn't plan for."""
        found = re.findall(r"model\s+(\w+)\s+\{", self.schema)
        expected = ["User", "JournalEntry", "CheckIn", "Note", "Photo", "ChatMessage"]
        self.assertEqual(set(found), set(expected))


if __name__ == "__main__":
    unittest.main()
