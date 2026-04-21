from __future__ import annotations

import unittest

from pathlib import Path
import tempfile

from src.cli.chat import SYSTEM_PROMPT, build_context, filter_relevant_points, guess_article_titles, is_usable_answer, normalize_title, normalize_zim_name, synthesize_answer, title_matches_guess, trim_wikipedia_text


class ChatCliTests(unittest.TestCase):
    def test_system_prompt_is_apocalypse_oriented(self) -> None:
        self.assertIn("apocalypse", SYSTEM_PROMPT.lower())
        self.assertIn("Do not default to \"go see a doctor\"", SYSTEM_PROMPT)
        self.assertIn("field-expedient", SYSTEM_PROMPT)
        self.assertIn("Write a real explanation in complete sentences", SYSTEM_PROMPT)

    def test_build_context_uses_payload_text_and_citations(self) -> None:
        points = [
            {
                "score": 0.91,
                "payload": {
                    "source_file": "who_psychological_first_aid_guide.pdf",
                    "chunk_index": 7,
                    "text": "Psychological first aid includes practical support and listening.",
                },
            },
            {
                "score": 0.82,
                "payload": {
                    "source_file": "ready_emergency_supply_list.pdf",
                    "chunk_index": 2,
                    "text": "Keep water, food, and medicines ready.",
                },
            },
        ]

        context, used = build_context(points, max_chars=10_000)

        self.assertIn("[who_psychological_first_aid_guide.pdf#chunk_7", context)
        self.assertIn("Psychological first aid includes practical support", context)
        self.assertEqual(len(used), 2)
        self.assertEqual(used[0]["source_file"], "who_psychological_first_aid_guide.pdf")

    def test_filter_relevant_points_rejects_irrelevant_low_overlap_chunks(self) -> None:
        points = [
            {
                "score": 0.59,
                "payload": {
                    "source_file": "who_psychological_first_aid_guide.pdf",
                    "chunk_index": 46,
                    "text": "Psychological first aid focuses on listening and practical comfort.",
                },
            }
        ]

        kept = filter_relevant_points(points, "i'm afraid my leg is broken, what do I do?")
        self.assertEqual(kept, [])

    def test_filter_relevant_points_keeps_ptsd_related_who_chunk(self) -> None:
        points = [
            {
                "score": 0.58,
                "payload": {
                    "source_file": "who_psychological_first_aid_guide.pdf",
                    "chunk_index": 12,
                    "text": "Some people may develop post traumatic stress disorder after extreme events.",
                },
            }
        ]

        kept = filter_relevant_points(points, "I think I have PTSD")
        self.assertEqual(len(kept), 1)

    def test_normalize_zim_name_strips_version_suffix(self) -> None:
        self.assertEqual(
            normalize_zim_name(Path("wikipedia_en_all_nopic_2026-03.zim")),
            "wikipedia_en_all_nopic",
        )

    def test_guess_article_titles_extracts_subject_from_question(self) -> None:
        guessed = guess_article_titles("who was adolf hitler?")
        self.assertIn("adolf hitler", [item.lower() for item in guessed])

    def test_guess_article_titles_extracts_core_subject_from_treatment_question(self) -> None:
        guessed = guess_article_titles("what is the antidote for cyanide?")
        lowered = [item.lower() for item in guessed]
        self.assertIn("cyanide", lowered)
        self.assertEqual(lowered[0], "cyanide")

    def test_normalize_title_collapses_related_punctuation(self) -> None:
        self.assertEqual(normalize_title("Adolf Hitler's cult of personality"), "adolf hitler s cult of personality")
        self.assertEqual(normalize_title("Adolf Hitler"), "adolf hitler")

    def test_title_matches_guess_allows_specific_variants(self) -> None:
        self.assertTrue(title_matches_guess("Cyanide poisoning", ["cyanide"]))
        self.assertFalse(title_matches_guess("Mental health of Adolf Hitler", ["adolf hitler"]))

    def test_synthesize_answer_handles_fracture_question(self) -> None:
        answer = synthesize_answer(
            "i think my leg is broken, what do I do?",
            [
                {
                    "source_file": "tccc_module_17_fractures_splinting.pdf",
                    "chunk_index": 2,
                    "text": "ON (breathing)\nC CIRCULATION\nS SPLINTING\nSplint the injured extremity and immobilize the joints above and below the fracture. Check distal circulation before and after splinting.",
                }
            ],
        )
        self.assertIn("fracture", answer.lower())
        self.assertIn("splint", answer.lower())
        self.assertIn("[tccc_module_17_fractures_splinting.pdf#chunk_2]", answer)
        self.assertNotIn("ON (breathing)", answer)

    def test_synthesize_answer_handles_who_question(self) -> None:
        answer = synthesize_answer(
            "who was adolf hitler?",
            [
                {
                    "source_file": "wikipedia_en_all_nopic_2026-03:Adolf Hitler",
                    "chunk_index": "Adolf_Hitler",
                    "text": "Adolf Hitler was an Austrian-born German politician who led Nazi Germany from 1933 to 1945. He was central to the rise of Nazism and the start of World War II. In office 1933 to 1945. Preceded by Kurt von Schleicher.",
                }
            ],
        )
        self.assertIn("Adolf Hitler was", answer)
        self.assertIn("World War II", answer)
        self.assertNotIn("Preceded by", answer)

    def test_trim_wikipedia_text_prefers_lead_prose(self) -> None:
        text = trim_wikipedia_text(
            "Adolf Hitler\nFormal portrait, 1938\nIn office\nAdolf Hitler was an Austrian-born German politician who led Nazi Germany.\n"
            "He was central to the rise of Nazism and the start of World War II.\nPreceded by\nSucceeded by"
        )
        self.assertIn("Austrian-born German politician", text)
        self.assertNotIn("Preceded by", text)

    def test_is_usable_answer_rejects_blank_or_citation_only(self) -> None:
        self.assertFalse(is_usable_answer(""))
        self.assertFalse(is_usable_answer("[foo.pdf#chunk_1]"))
        self.assertTrue(is_usable_answer("This is a real answer. It has two sentences."))


if __name__ == "__main__":
    unittest.main()
