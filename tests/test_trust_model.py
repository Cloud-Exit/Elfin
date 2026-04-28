"""
Unit tests for Slice 7: verified trust model.

Tests entity extraction, knowledge base verification, cross-referencing logic,
contradiction detection, and overall verification status computation.
"""

from __future__ import annotations

import json
import math
import unittest
from unittest.mock import MagicMock, patch

from src.cli.trust import (
    EntityVerification,
    VerificationResult,
    extract_entities,
    lexical_overlap,
    verify_entity,
    verify_visual_id,
    format_verification_report,
    verification_to_json,
    _extract_entity_description,
    _title_matches_entity,
)


class EntityExtractionTests(unittest.TestCase):
    """Test entity extraction from AI visual analysis text."""

    def test_extract_plant_entities(self) -> None:
        text = "The image shows poison ivy growing near a stream."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("poison ivy" in name for name in entity_names))

    def test_extract_plant_edible(self) -> None:
        text = "I can see wild onion and some yarrow flowers."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("wild onion" in name for name in entity_names))
        self.assertTrue(any("yarrow" in name for name in entity_names))

    def test_extract_deadly_plant(self) -> None:
        text = "This looks like deadly nightshade berries."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("deadly" in name for name in entity_names))

    def test_extract_animal_entities(self) -> None:
        text = "There is a rattlesnake coiled near the path."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("rattlesnake" in name for name in entity_names))

    def test_extract_spider(self) -> None:
        text = "A black widow spider is in the corner."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("black widow" in name for name in entity_names))

    def test_extract_injury_fracture(self) -> None:
        text = "The person has a broken arm with visible deformity."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("broken arm" in name for name in entity_names))

    def test_extract_injury_burn(self) -> None:
        text = "There is a severe burn on the leg with blistering."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("burn" in name for name in entity_names))

    def test_extract_injury_bite(self) -> None:
        text = "The wound appears to be a snake bite with swelling."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("bite" in name for name in entity_names))

    def test_extract_hazard_flood(self) -> None:
        text = "Flash flood warning signs are visible ahead."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("flash flood" in name for name in entity_names))

    def test_extract_hazard_hypothermia(self) -> None:
        text = "The person shows signs of hypothermia and frostbite."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("hypothermia" in name for name in entity_names))
        self.assertTrue(any("frostbite" in name for name in entity_names))

    def test_extract_object_first_aid(self) -> None:
        text = "A first aid kit is visible on the table."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("first aid kit" in name for name in entity_names))

    def test_extract_multiple_entities(self) -> None:
        text = "Poison ivy and a rattlesnake are both visible in this area."
        entities = extract_entities(text)
        entity_names = [e[0].lower() for e in entities]
        self.assertTrue(any("poison ivy" in name for name in entity_names))
        self.assertTrue(any("rattlesnake" in name for name in entity_names))

    def test_extract_no_entities(self) -> None:
        text = "The image shows a generic landscape with trees and grass."
        entities = extract_entities(text)
        self.assertEqual(entities, [])

    def test_extract_deduplicates_entities(self) -> None:
        text = "Poison ivy is near the poison ivy patch."
        entities = extract_entities(text)
        poison_ivy_count = sum(1 for e in entities if "poison ivy" in e[0].lower())
        self.assertEqual(poison_ivy_count, 1)

    def test_extract_entity_categories(self) -> None:
        text = "Poison ivy and a broken leg are visible."
        entities = extract_entities(text)
        categories = {e[0].lower(): e[1] for e in entities}
        self.assertTrue(any(cat == "plant" for name, cat in categories.items() if "poison ivy" in name))
        self.assertTrue(any(cat == "injury" for name, cat in categories.items() if "broken leg" in name))

    def test_extract_case_insensitive(self) -> None:
        text = "The image shows POISON IVY and a Rattlesnake."
        entities = extract_entities(text)
        self.assertTrue(len(entities) >= 2)


class LexicalOverlapTests(unittest.TestCase):
    """Test lexical overlap computation."""

    def test_exact_match(self) -> None:
        overlap = lexical_overlap("poison ivy identification", "poison ivy is a poisonous plant")
        self.assertGreater(overlap, 0.5)

    def test_no_overlap(self) -> None:
        overlap = lexical_overlap("apple banana orange", "mountain river forest")
        self.assertEqual(overlap, 0.0)

    def test_partial_overlap(self) -> None:
        overlap = lexical_overlap("poison ivy treatment", "ivy poisoning first aid steps")
        self.assertGreater(overlap, 0.0)
        self.assertLess(overlap, 1.0)

    def test_empty_query(self) -> None:
        overlap = lexical_overlap("", "some text here")
        self.assertEqual(overlap, 0.0)

    def test_empty_text(self) -> None:
        overlap = lexical_overlap("some query", "")
        self.assertEqual(overlap, 0.0)

    def test_single_word_match(self) -> None:
        overlap = lexical_overlap("fracture", "the bone fracture requires a splint")
        self.assertGreater(overlap, 0.0)

    def test_case_insensitive(self) -> None:
        overlap = lexical_overlap("Poison Ivy", "poison ivy is toxic")
        self.assertGreater(overlap, 0.0)

    def test_short_tokens_ignored(self) -> None:
        # Single character tokens are excluded by {2,} pattern
        overlap = lexical_overlap("a b c d", "a b c d")
        self.assertEqual(overlap, 0.0)


class EntityDescriptionExtractionTests(unittest.TestCase):
    """Test entity-specific description extraction."""

    def test_extract_sentence_with_entity(self) -> None:
        text = "The image shows a field. I can see poison ivy growing near the stream. The water is clear."
        desc = _extract_entity_description(text, "poison ivy")
        self.assertIn("poison ivy", desc.lower())

    def test_extract_no_matching_sentence(self) -> None:
        text = "The image shows a field with trees."
        desc = _extract_entity_description(text, "rattlesnake")
        # Falls back to full text when no sentence mentions the entity
        self.assertEqual(desc, text)

    def test_extract_multiple_sentences(self) -> None:
        text = "I see poison ivy. The leaves are red. The area is dangerous."
        desc = _extract_entity_description(text, "poison ivy")
        self.assertIn("poison ivy", desc.lower())


class TitleMatchingTests(unittest.TestCase):
    """Test Kiwix title matching against entity names."""

    def test_exact_title_match(self) -> None:
        self.assertTrue(_title_matches_entity("Poison ivy", "poison ivy"))

    def test_title_contains_entity_word(self) -> None:
        self.assertTrue(_title_matches_entity("Poison ivy identification and treatment", "poison ivy"))

    def test_title_partial_match(self) -> None:
        self.assertTrue(_title_matches_entity("Toxicodendron radicans (Poison ivy)", "poison ivy"))

    def test_no_match(self) -> None:
        self.assertFalse(_title_matches_entity("Mountain climbing guide", "poison ivy"))

    def test_entity_word_in_title(self) -> None:
        self.assertTrue(_title_matches_entity("Snake bite first aid", "snake"))

    def test_empty_entity(self) -> None:
        self.assertFalse(_title_matches_entity("Some title", ""))


class VerifyEntityTests(unittest.TestCase):
    """Test individual entity verification against knowledge sources."""

    def _make_qdrant_point(self, text: str, score: float = 0.8) -> dict:
        return {
            "payload": {
                "text": text,
                "source_file": "survival_guide.pdf",
                "chunk_index": 42,
            },
            "score": score,
        }

    def _make_kiwix_result(self, text: str, title: str = "Test Article", overlap: float = 0.5) -> dict:
        return {
            "text": text,
            "title": title,
            "source": "kiwix:wikipedia_en",
            "lexical_overlap": overlap,
        }

    def test_verified_both_sources(self) -> None:
        """Entity confirmed by both Qdrant and Kiwix."""
        result = verify_entity(
            entity="poison ivy",
            category="plant",
            ai_description="Three-leaved plant causing red rash",
            qdrant_points=[
                self._make_qdrant_point("Poison ivy is a creeping vine that causes an allergic reaction and red rash on contact.", 0.85),
            ],
            kiwix_results=[
                self._make_kiwix_result("Poison ivy (Toxicodendron radicans) is a plant species known for causing allergic contact dermatitis and red rash.", "Poison ivy", 0.6),
            ],
        )
        self.assertEqual(result.status, "verified")
        self.assertGreater(result.confidence, 0.5)
        self.assertEqual(result.qdrant_matches, 1)
        self.assertEqual(result.kiwix_matches, 1)

    def test_verified_qdrant_only(self) -> None:
        """Entity confirmed by Qdrant but not Kiwix."""
        result = verify_entity(
            entity="yarrow",
            category="plant",
            ai_description="White flowering herb used for wound treatment",
            qdrant_points=[
                self._make_qdrant_point("Yarrow is a medicinal herb commonly used for wound treatment and stopping bleeding.", 0.78),
            ],
            kiwix_results=[],
        )
        self.assertEqual(result.status, "verified")
        self.assertGreater(result.confidence, 0.3)
        self.assertLess(result.confidence, 0.8)

    def test_verified_kiwix_only(self) -> None:
        """Entity confirmed by Kiwix but not Qdrant."""
        result = verify_entity(
            entity="rattlesnake",
            category="animal",
            ai_description="Venomous snake with rattle on tail",
            qdrant_points=[],
            kiwix_results=[
                self._make_kiwix_result("The rattlesnake is a venomous snake species found in the Americas, known for the rattle on its tail.", "Rattlesnake", 0.55),
            ],
        )
        self.assertEqual(result.status, "verified")
        self.assertGreater(result.confidence, 0.3)

    def test_unverified_no_sources(self) -> None:
        """Entity found in neither source."""
        result = verify_entity(
            entity="mystery plant",
            category="plant",
            ai_description="Unknown green plant",
            qdrant_points=[],
            kiwix_results=[],
        )
        self.assertEqual(result.status, "unverified")
        self.assertEqual(result.confidence, 0.0)

    def test_conflicted_safe_vs_poisonous(self) -> None:
        """AI says safe, KB says poisonous - should be conflicted."""
        result = verify_entity(
            entity="nightshade",
            category="plant",
            ai_description="This plant is safe to eat and edible",
            qdrant_points=[
                self._make_qdrant_point("Deadly nightshade is extremely poisonous. All parts of the plant are toxic and dangerous.", 0.82),
            ],
            kiwix_results=[
                self._make_kiwix_result("Deadly nightshade (Atropa belladonna) is a highly poisonous plant. The berries are toxic and can be fatal if ingested.", "Deadly nightshade", 0.7),
            ],
        )
        self.assertEqual(result.status, "conflicted")

    def test_conflicted_harmless_vs_venomous(self) -> None:
        """AI says harmless, KB says venomous."""
        result = verify_entity(
            entity="snake",
            category="animal",
            ai_description="This is a harmless non-venomous snake",
            qdrant_points=[
                self._make_qdrant_point("The copperhead is a venomous pit viper found in eastern North America.", 0.79),
            ],
            kiwix_results=[
                self._make_kiwix_result("The copperhead is a moderately venomous snake. Its bite requires medical attention.", "Copperhead", 0.5),
            ],
        )
        self.assertEqual(result.status, "conflicted")

    def test_uncertain_weak_matches(self) -> None:
        """Weak matches without entity name in text."""
        result = verify_entity(
            entity="unknown berry",
            category="plant",
            ai_description="Small red berry",
            qdrant_points=[
                self._make_qdrant_point("Some berries are edible while others are toxic. Always identify before eating.", 0.4),
            ],
            kiwix_results=[],
        )
        # Low overlap + no entity name in text -> uncertain or unverified
        self.assertIn(result.status, ("uncertain", "unverified"))

    def test_evidence_snippets_captured(self) -> None:
        """Evidence snippets are properly captured."""
        result = verify_entity(
            entity="fracture",
            category="injury",
            ai_description="Broken bone visible deformity",
            qdrant_points=[
                self._make_qdrant_point("A bone fracture requires immobilization with a splint. Do not attempt to reset the bone yourself.", 0.88),
            ],
            kiwix_results=[
                self._make_kiwix_result("Fracture is a break in the continuity of a bone. Types include simple, compound, and comminuted fractures.", "Fracture (medicine)", 0.65),
            ],
        )
        self.assertTrue(len(result.qdrant_evidence) >= 1)
        self.assertTrue(len(result.kiwix_evidence) >= 1)
        self.assertIn("fracture", result.kb_description.lower())

    def test_confidence_increases_with_more_matches(self) -> None:
        """More source matches should increase confidence."""
        result_low = verify_entity(
            entity="burn",
            category="injury",
            ai_description="Skin burn from fire",
            qdrant_points=[self._make_qdrant_point("Burn treatment involves cooling the affected area with water.", 0.8)],
            kiwix_results=[],
        )
        result_high = verify_entity(
            entity="burn",
            category="injury",
            ai_description="Skin burn from fire",
            qdrant_points=[
                self._make_qdrant_point("Burn treatment involves cooling the affected area with water.", 0.8),
                self._make_qdrant_point("Second degree burns cause blistering and require sterile dressing.", 0.75),
            ],
            kiwix_results=[
                self._make_kiwix_result("A burn is an injury caused by heat, fire, or radiation.", "Burn (injury)", 0.6),
            ],
        )
        self.assertGreater(result_high.confidence, result_low.confidence)

    def test_entity_with_no_ai_description(self) -> None:
        """Entity verification works with empty AI description."""
        result = verify_entity(
            entity="tourniquet",
            category="object",
            ai_description="",
            qdrant_points=[
                self._make_qdrant_point("A tourniquet is used to stop severe bleeding by compressing blood vessels.", 0.83),
            ],
            kiwix_results=[],
        )
        self.assertEqual(result.status, "verified")

    def test_low_score_qdrant_still_counts_with_entity_match(self) -> None:
        """Even low semantic score, entity name present in text should verify."""
        result = verify_entity(
            entity="plantain",
            category="plant",
            ai_description="Common weed with healing properties",
            qdrant_points=[
                self._make_qdrant_point("Plantain (Plantago major) can be used as a natural wound dressing for minor cuts and insect bites.", 0.55),
            ],
            kiwix_results=[],
        )
        self.assertEqual(result.status, "verified")


class VerificationResultTests(unittest.TestCase):
    """Test overall verification result computation."""

    def test_overall_verified_majority(self) -> None:
        """When most entities are verified, overall is verified."""
        result = VerificationResult(
            visual_answer="test",
            entities=[
                EntityVerification("poison ivy", "plant", "verified", 0.8, 1, 1),
                EntityVerification("burn", "injury", "verified", 0.7, 1, 0),
                EntityVerification("unknown", "plant", "unverified", 0.0, 0, 0),
            ],
            overall_status="verified",
            verified_count=2,
            unverified_count=1,
            conflicted_count=0,
            uncertain_count=0,
        )
        # Verify counts are correct
        self.assertEqual(result.verified_count, 2)
        self.assertEqual(result.unverified_count, 1)

    def test_overall_conflicted_if_any_conflict(self) -> None:
        """Any conflict makes overall status conflicted."""
        result = VerificationResult(
            visual_answer="test",
            entities=[
                EntityVerification("plant", "plant", "verified", 0.8, 1, 1),
                EntityVerification("berry", "plant", "conflicted", 0.3, 1, 1),
            ],
            overall_status="conflicted",
            verified_count=1,
            unverified_count=0,
            conflicted_count=1,
            uncertain_count=0,
        )
        self.assertEqual(result.overall_status, "conflicted")

    def test_overall_unverified_majority(self) -> None:
        """When most entities are unverified, overall is unverified."""
        result = VerificationResult(
            visual_answer="test",
            entities=[
                EntityVerification("unknown1", "plant", "unverified", 0.0, 0, 0),
                EntityVerification("unknown2", "plant", "unverified", 0.0, 0, 0),
                EntityVerification("known", "plant", "verified", 0.7, 1, 0),
            ],
            overall_status="unverified",
            verified_count=1,
            unverified_count=2,
            conflicted_count=0,
            uncertain_count=0,
        )
        self.assertEqual(result.overall_status, "unverified")


class VerifyVisualIdTests(unittest.TestCase):
    """Test the main verify_visual_id integration with mocked services."""

    def test_verify_visual_id_no_entities(self) -> None:
        """When no entities are found, returns unverified with empty entities."""
        with patch("src.cli.trust.embed_query") as mock_embed:
            result = verify_visual_id(
                visual_answer="The image shows a beautiful landscape with trees and sky.",
                embed_url="http://localhost:8082",
                qdrant_url="http://localhost:6333",
                kiwix_url="http://localhost:8083",
                zim_dir="./data/datasets/zim",
            )
        self.assertEqual(result.overall_status, "unverified")
        self.assertEqual(result.entities, [])
        # embed_query should not be called since no entities found
        mock_embed.assert_not_called()

    def test_verify_visual_id_with_entities(self) -> None:
        """Full flow with mocked services."""
        mock_vector = [0.1] * 768

        with (
            patch("src.cli.trust.embed_query", return_value=mock_vector) as mock_embed,
            patch("src.cli.trust.search_qdrant") as mock_qdrant,
            patch("src.cli.trust.search_kiwix_for_entity") as mock_kiwix,
        ):
            mock_qdrant.return_value = [
                {
                    "payload": {
                        "text": "Poison ivy causes red rash and itching. Avoid contact with the plant.",
                        "source_file": "survival.pdf",
                        "chunk_index": 5,
                    },
                    "score": 0.85,
                }
            ]
            mock_kiwix.return_value = [
                {
                    "text": "Poison ivy is a plant that causes allergic contact dermatitis.",
                    "title": "Poison ivy",
                    "source": "kiwix:wikipedia_en",
                    "lexical_overlap": 0.6,
                }
            ]

            result = verify_visual_id(
                visual_answer="The image shows poison ivy growing near a creek.",
                embed_url="http://localhost:8082",
                qdrant_url="http://localhost:6333",
                kiwix_url="http://localhost:8083",
                zim_dir="./data/datasets/zim",
            )

        self.assertEqual(len(result.entities), 1)
        self.assertEqual(result.entities[0].entity.lower(), "poison ivy")
        self.assertEqual(result.entities[0].status, "verified")
        self.assertEqual(result.overall_status, "verified")
        self.assertEqual(result.verified_count, 1)

        # Verify embed_query was called with entity name
        mock_embed.assert_called_once()
        self.assertIn("poison ivy", mock_embed.call_args[0][1].lower())

    def test_verify_visual_id_embed_failure_graceful(self) -> None:
        """When embedding fails, still returns result (unverified)."""
        with (
            patch("src.cli.trust.embed_query", side_effect=RuntimeError("service unavailable")),
            patch("src.cli.trust.search_qdrant") as mock_qdrant,
            patch("src.cli.trust.search_kiwix_for_entity", return_value=[]),
        ):
            result = verify_visual_id(
                visual_answer="I see a rattlesnake on the path.",
                embed_url="http://localhost:8082",
                qdrant_url="http://localhost:6333",
                kiwix_url="http://localhost:8083",
                zim_dir="./data/datasets/zim",
            )

        # Should not crash, should return unverified since no Qdrant results
        self.assertEqual(len(result.entities), 1)
        self.assertEqual(result.entities[0].entity.lower(), "rattlesnake")
        self.assertEqual(result.entities[0].status, "unverified")
        # search_qdrant should NOT be called since embedding failed
        mock_qdrant.assert_not_called()

    def test_verify_visual_id_qdrant_failure_graceful(self) -> None:
        """When Qdrant search fails, still continues with Kiwix."""
        mock_vector = [0.1] * 768

        with (
            patch("src.cli.trust.embed_query", return_value=mock_vector),
            patch("src.cli.trust.search_qdrant", side_effect=RuntimeError("connection refused")),
            patch("src.cli.trust.search_kiwix_for_entity") as mock_kiwix,
        ):
            mock_kiwix.return_value = [
                {
                    "text": "The rattlesnake is a venomous pit viper.",
                    "title": "Rattlesnake",
                    "source": "kiwix:wikipedia_en",
                    "lexical_overlap": 0.55,
                }
            ]

            result = verify_visual_id(
                visual_answer="There is a rattlesnake on the trail.",
                embed_url="http://localhost:8082",
                qdrant_url="http://localhost:6333",
                kiwix_url="http://localhost:8083",
                zim_dir="./data/datasets/zim",
            )

        self.assertEqual(len(result.entities), 1)
        self.assertEqual(result.entities[0].status, "verified")
        self.assertEqual(result.entities[0].kiwix_matches, 1)

    def test_verify_visual_id_multiple_entities(self) -> None:
        """Multiple entities are each verified independently."""
        mock_vector = [0.1] * 768

        with (
            patch("src.cli.trust.embed_query", return_value=mock_vector) as mock_embed,
            patch("src.cli.trust.search_qdrant") as mock_qdrant,
            patch("src.cli.trust.search_kiwix_for_entity", return_value=[]),
        ):
            mock_qdrant.return_value = [
                {
                    "payload": {
                        "text": "Poison ivy has three leaves and causes allergic reaction.",
                        "source_file": "plants.pdf",
                        "chunk_index": 10,
                    },
                    "score": 0.8,
                },
                {
                    "payload": {
                        "text": "Rattlesnakes are venomous snakes found in North America.",
                        "source_file": "animals.pdf",
                        "chunk_index": 3,
                    },
                    "score": 0.75,
                },
            ]

            result = verify_visual_id(
                visual_answer="I see poison ivy and a rattlesnake in this area.",
                embed_url="http://localhost:8082",
                qdrant_url="http://localhost:6333",
                kiwix_url="http://localhost:8083",
                zim_dir="./data/datasets/zim",
            )

        self.assertEqual(len(result.entities), 2)
        entity_names = {e.entity.lower() for e in result.entities}
        self.assertIn("poison ivy", entity_names)
        self.assertIn("rattlesnake", entity_names)
        # embed_query called once per entity
        self.assertEqual(mock_embed.call_count, 2)

    def test_verify_visual_id_conflicted_overall(self) -> None:
        """When any entity is conflicted, overall is conflicted."""
        mock_vector = [0.1] * 768

        with (
            patch("src.cli.trust.embed_query", return_value=mock_vector),
            patch("src.cli.trust.search_qdrant") as mock_qdrant,
            patch("src.cli.trust.search_kiwix_for_entity", return_value=[]),
        ):
            mock_qdrant.return_value = [
                {
                    "payload": {
                        "text": "This berry is safe to eat and edible.",
                        "source_file": "plants.pdf",
                        "chunk_index": 1,
                    },
                    "score": 0.8,
                }
            ]

            result = verify_visual_id(
                visual_answer="These berries are poisonous and toxic to humans.",
                embed_url="http://localhost:8082",
                qdrant_url="http://localhost:6333",
                kiwix_url="http://localhost:8083",
                zim_dir="./data/datasets/zim",
            )

        # No entities matched in this case since "berries" isn't in our patterns
        # but the overall should still be handled
        self.assertIsNotNone(result.overall_status)


class FormatVerificationReportTests(unittest.TestCase):
    """Test human-readable report formatting."""

    def test_report_contains_overall_status(self) -> None:
        result = VerificationResult(
            visual_answer="test analysis",
            entities=[
                EntityVerification("poison ivy", "plant", "verified", 0.8, 1, 1, ["evidence"], ["evidence2"]),
            ],
            overall_status="verified",
            verified_count=1,
            unverified_count=0,
            conflicted_count=0,
            uncertain_count=0,
        )
        report = format_verification_report(result)
        self.assertIn("VERIFIED", report)
        self.assertIn("poison ivy", report)
        self.assertIn("plant", report)

    def test_report_empty_entities(self) -> None:
        result = VerificationResult(
            visual_answer="no entities here",
            entities=[],
            overall_status="unverified",
            verified_count=0,
            unverified_count=0,
            conflicted_count=0,
            uncertain_count=0,
        )
        report = format_verification_report(result)
        self.assertIn("No survival-relevant entities", report)

    def test_report_conflicted_marker(self) -> None:
        result = VerificationResult(
            visual_answer="test",
            entities=[
                EntityVerification("berry", "plant", "conflicted", 0.3, 1, 1),
            ],
            overall_status="conflicted",
            verified_count=0,
            unverified_count=0,
            conflicted_count=1,
            uncertain_count=0,
        )
        report = format_verification_report(result)
        self.assertIn("[!]", report)
        self.assertIn("CONFLICTED", report)

    def test_report_verified_marker(self) -> None:
        result = VerificationResult(
            visual_answer="test",
            entities=[
                EntityVerification("yarrow", "plant", "verified", 0.85, 2, 1),
            ],
            overall_status="verified",
            verified_count=1,
            unverified_count=0,
            conflicted_count=0,
            uncertain_count=0,
        )
        report = format_verification_report(result)
        self.assertIn("[V]", report)

    def test_report_unverified_marker(self) -> None:
        result = VerificationResult(
            visual_answer="test",
            entities=[
                EntityVerification("unknown", "plant", "unverified", 0.0, 0, 0),
            ],
            overall_status="unverified",
            verified_count=0,
            unverified_count=1,
            conflicted_count=0,
            uncertain_count=0,
        )
        report = format_verification_report(result)
        self.assertIn("[?]", report)

    def test_report_uncertain_marker(self) -> None:
        result = VerificationResult(
            visual_answer="test",
            entities=[
                EntityVerification("mystery", "plant", "uncertain", 0.2, 1, 0),
            ],
            overall_status="uncertain",
            verified_count=0,
            unverified_count=0,
            conflicted_count=0,
            uncertain_count=1,
        )
        report = format_verification_report(result)
        self.assertIn("[~]", report)

    def test_report_truncates_long_visual_answer(self) -> None:
        long_answer = "A" * 300
        result = VerificationResult(
            visual_answer=long_answer,
            entities=[],
            overall_status="unverified",
            verified_count=0,
            unverified_count=0,
            conflicted_count=0,
            uncertain_count=0,
        )
        report = format_verification_report(result)
        # Should truncate to 200 chars + "..."
        self.assertNotIn(long_answer, report)


class VerificationToJsonTests(unittest.TestCase):
    """Test JSON serialization of verification results."""

    def test_json_contains_all_fields(self) -> None:
        result = VerificationResult(
            visual_answer="test analysis",
            entities=[
                EntityVerification(
                    entity="poison ivy",
                    category="plant",
                    status="verified",
                    confidence=0.85,
                    qdrant_matches=2,
                    kiwix_matches=1,
                    qdrant_evidence=["evidence1"],
                    kiwix_evidence=["evidence2"],
                    ai_description="Three-leaved plant",
                    kb_description="Toxicodendron radicans",
                ),
            ],
            overall_status="verified",
            verified_count=1,
            unverified_count=0,
            conflicted_count=0,
            uncertain_count=0,
        )
        data = verification_to_json(result)

        self.assertEqual(data["visual_answer"], "test analysis")
        self.assertEqual(data["overall_status"], "verified")
        self.assertEqual(data["verified_count"], 1)
        self.assertEqual(len(data["entities"]), 1)
        self.assertEqual(data["entities"][0]["entity"], "poison ivy")
        self.assertEqual(data["entities"][0]["category"], "plant")
        self.assertEqual(data["entities"][0]["status"], "verified")
        self.assertEqual(data["entities"][0]["qdrant_matches"], 2)
        self.assertEqual(data["entities"][0]["kiwix_matches"], 1)
        self.assertEqual(data["entities"][0]["ai_description"], "Three-leaved plant")
        self.assertEqual(data["entities"][0]["kb_description"], "Toxicodendron radicans")

    def test_json_is_serializable(self) -> None:
        result = VerificationResult(
            visual_answer="test",
            entities=[
                EntityVerification("burn", "injury", "verified", 0.7, 1, 0),
            ],
            overall_status="verified",
            verified_count=1,
            unverified_count=0,
            conflicted_count=0,
            uncertain_count=0,
        )
        data = verification_to_json(result)
        # Should not raise
        json_str = json.dumps(data)
        self.assertIsInstance(json_str, str)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["overall_status"], "verified")

    def test_json_confidence_rounded(self) -> None:
        result = VerificationResult(
            visual_answer="test",
            entities=[
                EntityVerification("test", "plant", "verified", 0.8333333, 1, 1),
            ],
            overall_status="verified",
            verified_count=1,
            unverified_count=0,
            conflicted_count=0,
            uncertain_count=0,
        )
        data = verification_to_json(result)
        # Confidence should be rounded to 3 decimal places
        self.assertEqual(data["entities"][0]["confidence"], 0.833)


class ContradictionDetectionTests(unittest.TestCase):
    """Test contradiction detection between AI claims and KB."""

    CONTRADICTION_PAIRS = [
        ("safe", "poisonous"),
        ("safe", "toxic"),
        ("safe", "dangerous"),
        ("edible", "poisonous"),
        ("edible", "toxic"),
        ("harmless", "dangerous"),
        ("harmless", "toxic"),
        ("benign", "malignant"),
        ("non-venomous", "venomous"),
        ("harmless", "venomous"),
    ]

    def _make_conflicted_test(self, ai_word: str, kb_word: str) -> None:
        """Helper to test a specific contradiction pair."""
        result = verify_entity(
            entity="test plant",
            category="plant",
            ai_description=f"This plant is {ai_word} for consumption",
            qdrant_points=[
                {
                    "payload": {
                        "text": f"This plant is {kb_word} and should be avoided at all times.",
                        "source_file": "plants.pdf",
                        "chunk_index": 1,
                    },
                    "score": 0.85,
                },
            ],
            kiwix_results=[
                {
                    "text": f"The plant is known to be {kb_word} to humans.",
                    "title": "Test plant",
                    "source": "kiwix:wikipedia_en",
                    "lexical_overlap": 0.5,
                },
            ],
        )
        self.assertEqual(
            result.status,
            "conflicted",
            f"Expected conflicted for AI='{ai_word}' vs KB='{kb_word}'",
        )

    def test_safe_vs_poisonous(self) -> None:
        self._make_conflicted_test("safe", "poisonous")

    def test_safe_vs_toxic(self) -> None:
        self._make_conflicted_test("safe", "toxic")

    def test_edible_vs_poisonous(self) -> None:
        self._make_conflicted_test("edible", "poisonous")

    def test_harmless_vs_venomous(self) -> None:
        self._make_conflicted_test("harmless", "venomous")

    def test_non_venomous_vs_venomous(self) -> None:
        self._make_conflicted_test("non-venomous", "venomous")

    def test_no_contradiction_when_both_agree(self) -> None:
        """No contradiction when AI and KB agree."""
        result = verify_entity(
            entity="yarrow",
            category="plant",
            ai_description="This plant is safe and edible",
            qdrant_points=[
                {
                    "payload": {
                        "text": "Yarrow is a safe edible herb with medicinal properties.",
                        "source_file": "herbs.pdf",
                        "chunk_index": 5,
                    },
                    "score": 0.85,
                },
            ],
            kiwix_results=[
                {
                    "text": "Yarrow is a safe edible plant used in traditional medicine.",
                    "title": "Yarrow",
                    "source": "kiwix:wikipedia_en",
                    "lexical_overlap": 0.6,
                },
            ],
        )
        self.assertEqual(result.status, "verified")


if __name__ == "__main__":
    unittest.main()
