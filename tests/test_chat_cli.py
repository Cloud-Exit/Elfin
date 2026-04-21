from __future__ import annotations

import unittest

from pathlib import Path
import tempfile
from unittest.mock import patch

from src.cli.chat import SYSTEM_PROMPT, ask_llama, build_context, build_kiwix_context, build_user_prompt, clean_wikipedia_prose, extract_visible_answer, fetch_guessed_kiwix_article, fetch_kiwix_article_text, filter_relevant_points, guess_article_titles, has_truncated_tail, is_usable_answer, merge_retrieved_sources, normalize_title, normalize_zim_name, overrelies_on_professional_care, parse_kiwix_result_href, preferred_kiwix_books, synthesize_answer, title_matches_guess, trim_to_complete_sentences, trim_wikipedia_text


class ChatCliTests(unittest.TestCase):
    def test_system_prompt_is_apocalypse_oriented(self) -> None:
        self.assertIn("apocalypse", SYSTEM_PROMPT.lower())
        self.assertIn("Do not default to \"go see a doctor\"", SYSTEM_PROMPT)
        self.assertIn("field-expedient", SYSTEM_PROMPT)
        self.assertIn("Write a real explanation in complete sentences", SYSTEM_PROMPT)
        self.assertIn("Paraphrase retrieved material in your own words", SYSTEM_PROMPT)
        self.assertIn("If you mention professional care", SYSTEM_PROMPT)

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

    def test_merge_retrieved_sources_combines_qdrant_and_kiwix(self) -> None:
        context, used = merge_retrieved_sources(
            [
                {
                    "source_file": "manual.pdf",
                    "chunk_index": 1,
                    "score": 0.9,
                    "lexical_overlap": 0.4,
                    "text": "Field manual guidance.",
                }
            ],
            [
                {
                    "source_file": "wikipedia_en_all_nopic_2026-03:Adolf Hitler",
                    "chunk_index": "Adolf_Hitler",
                    "score": None,
                    "lexical_overlap": 1.0,
                    "text": "Adolf Hitler was an Austrian-born German politician.",
                }
            ],
            max_chars=10000,
        )
        self.assertIn("manual.pdf#chunk_1", context)
        self.assertIn("wikipedia_en_all_nopic_2026-03:Adolf Hitler#chunk_Adolf_Hitler", context)
        self.assertEqual(len(used), 2)

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

    def test_guess_article_titles_recovers_from_truncated_auxiliary(self) -> None:
        guessed = guess_article_titles("who wa adolf hitler ?")
        self.assertEqual(guessed[0].lower(), "adolf hitler")

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

    def test_synthesize_answer_handles_infected_puncture_wound_question(self) -> None:
        answer = synthesize_answer(
            "I think i might have a serious leg infection because of a rusty nail, what do I do ?",
            [
                {
                    "source_file": "cdc_emergency_wound_care_after_disaster.pdf",
                    "chunk_index": 0,
                    "text": (
                        "Clean the wound with soap and clean water. Cover the wound with a waterproof bandage. "
                        "Watch for redness, swelling, oozing, or persistent soreness."
                    ),
                },
                {
                    "source_file": "tccc_sepsis_management_pfc.pdf",
                    "chunk_index": 25,
                    "text": (
                        "Signs of severe infection include fever, confusion, shortness of breath, a high heart rate, "
                        "or feeling clammy."
                    ),
                },
            ],
        )
        self.assertIn("Flush the wound thoroughly", answer)
        self.assertIn("cover it with the cleanest dressing", answer.lower())
        self.assertIn("fever", answer.lower())
        self.assertNotIn("seek immediate medical care", answer.lower())

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

    def test_clean_wikipedia_prose_removes_footnote_markers_and_spacing_artifacts(self) -> None:
        text = clean_wikipedia_prose(
            "Adolf Hitler [ a ] (20 April 1889 – 30 April 1945) was an Austrian-born German politician , "
            "leader of the Nazi Party . [ b ]"
        )
        self.assertNotIn("[ a ]", text)
        self.assertNotIn("[ b ]", text)
        self.assertIn("German politician,", text)
        self.assertIn("Nazi Party.", text)

    def test_extract_visible_answer_strips_reasoning_preamble(self) -> None:
        text = extract_visible_answer(
            "Thinking Process:\n1. think\n2. think\n<channel|>Adolf Hitler was a dictator."
        )
        self.assertEqual(text, "Adolf Hitler was a dictator.")

    def test_build_user_prompt_allows_general_knowledge_when_context_missing(self) -> None:
        prompt = build_user_prompt("who was adolf hitler?", "")
        self.assertIn("No retrieved context is available", prompt)
        self.assertIn("Answer from your general knowledge", prompt)
        self.assertIn("not a Wikipedia article", prompt)

    def test_build_user_prompt_requests_paraphrase_when_context_present(self) -> None:
        prompt = build_user_prompt("who was adolf hitler?", "[context]")
        self.assertIn("Paraphrase the source material in your own wording", prompt)

    def test_fetch_kiwix_article_text_falls_back_to_content_route(self) -> None:
        def fake_http_text(url: str, timeout: int = 60) -> str:
            if "/raw/" in url:
                raise RuntimeError("404")
            if "/content/" in url:
                return "<html><body><p>Adolf Hitler was an Austrian-born German politician.</p></body></html>"
            raise AssertionError(f"unexpected URL: {url}")

        with patch("src.cli.chat.http_text", side_effect=fake_http_text):
            text = fetch_kiwix_article_text(
                "http://localhost:8083",
                "wikipedia_en_all_nopic_2026-03",
                "A/Adolf_Hitler",
            )

        self.assertIn("Austrian-born German politician", text)

    def test_fetch_kiwix_article_text_supports_book_a_path_route(self) -> None:
        def fake_http_text(url: str, timeout: int = 60) -> str:
            if "/wikipedia_en_all_nopic_2026-03/A/Adolf_Hitler" in url:
                return "<html><body><p>Adolf Hitler was an Austrian-born German politician.</p></body></html>"
            raise RuntimeError("404")

        with patch("src.cli.chat.http_text", side_effect=fake_http_text):
            text = fetch_kiwix_article_text(
                "http://localhost:8083",
                "wikipedia_en_all_nopic_2026-03",
                "Adolf_Hitler",
            )

        self.assertIn("Austrian-born German politician", text)

    def test_fetch_kiwix_article_text_uses_paragraph_fallback_for_wikipedia(self) -> None:
        html = """
        <html><body>
        <p>Adolf Hitler was an Austrian-born German politician who led Nazi Germany from 1933 to 1945.</p>
        <p>He was central to the rise of Nazism and the start of World War II.</p>
        </body></html>
        """

        with patch("src.cli.chat.http_text", return_value=html), \
             patch("src.cli.chat.strip_html", return_value=""):
            text = fetch_kiwix_article_text(
                "http://localhost:8083",
                "wikipedia_en_all_nopic_2026-03",
                "Adolf_Hitler",
            )

        self.assertIn("Adolf Hitler was an Austrian-born German politician", text)
        self.assertIn("World War II", text)

    def test_fetch_guessed_kiwix_article_tries_titlecase_slug(self) -> None:
        def fake_fetch(kiwix_url: str, book: str, path: str) -> str:
            if path == "Adolf_Hitler":
                return (
                    "Adolf Hitler was an Austrian-born German politician who led Nazi Germany from 1933 to 1945. "
                    "He was central to the rise of Nazism and the start of World War II."
                )
            raise RuntimeError("404")

        with patch("src.cli.chat.fetch_kiwix_article_text", side_effect=fake_fetch):
            guessed = fetch_guessed_kiwix_article(
                "http://localhost:8083",
                "wikipedia_en_all_nopic_2026-03",
                "adolf hitler",
            )

        self.assertIsNotNone(guessed)
        assert guessed is not None
        self.assertEqual(guessed[0], "Adolf_Hitler")
        self.assertIn("Adolf Hitler was", guessed[1])

    def test_parse_kiwix_result_href_supports_book_a_path_scheme(self) -> None:
        parsed = parse_kiwix_result_href(
            "http://localhost:8083",
            "/wikipedia_en_all_nopic_2026-03/A/Adolf_Hitler",
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["book"], "wikipedia_en_all_nopic_2026-03")
        self.assertEqual(parsed["path"], "Adolf_Hitler")

    def test_preferred_kiwix_books_prioritizes_wikipedia_over_stackoverflow(self) -> None:
        books = preferred_kiwix_books(
            [
                "wikipedia_en_all_nopic_2026-03",
                "wikipedia_en_medicine_nopic_2026-04",
                "stackoverflow.com_en_all_2023-11",
            ]
        )
        self.assertEqual(
            books,
            ["wikipedia_en_all_nopic_2026-03", "wikipedia_en_medicine_nopic_2026-04"],
        )

    def test_build_kiwix_context_searches_subject_terms_for_exact_article(self) -> None:
        def fake_search(kiwix_url: str, book: str, query: str, limit: int) -> list[dict]:
            if query.lower() == "who was adolf hitler ?":
                return [
                    {
                        "book": book,
                        "path": "Mental_health_of_Adolf_Hitler",
                        "title": "Mental health of Adolf Hitler",
                        "browse_url": f"{kiwix_url}/content/{book}/Mental_health_of_Adolf_Hitler",
                    }
                ]
            if query.lower() == "adolf hitler":
                return [
                    {
                        "book": book,
                        "path": "Adolf_Hitler",
                        "title": "Adolf Hitler",
                        "browse_url": f"{kiwix_url}/content/{book}/Adolf_Hitler",
                    }
                ]
            return []

        def fake_fetch(kiwix_url: str, book: str, path: str) -> str:
            if path == "Adolf_Hitler":
                return (
                    "Adolf Hitler was an Austrian-born German politician who led Nazi Germany from 1933 to 1945. "
                    "He was central to the rise of Nazism and the start of World War II."
                )
            return "Mental health article"

        with patch("src.cli.chat.discover_kiwix_books", return_value=["wikipedia_en_all_nopic_2026-03"]), \
             patch("src.cli.chat.kiwix_suggest_titles", return_value=[]), \
             patch("src.cli.chat.fetch_guessed_kiwix_article", return_value=None), \
             patch("src.cli.chat.kiwix_search", side_effect=fake_search), \
             patch("src.cli.chat.fetch_kiwix_article_text", side_effect=fake_fetch):
            context, sources = build_kiwix_context(
                "http://localhost:8083",
                Path("/workspace/data/datasets/zim"),
                "who was adolf hitler ?",
                max_chars=3000,
            )

        self.assertIn("Adolf Hitler was an Austrian-born German politician", context)
        self.assertEqual(len(sources), 1)
        self.assertIn("Adolf Hitler", sources[0]["source_file"])

    def test_is_usable_answer_rejects_blank_or_citation_only(self) -> None:
        self.assertFalse(is_usable_answer(""))
        self.assertFalse(is_usable_answer("[foo.pdf#chunk_1]"))
        self.assertTrue(is_usable_answer("This is a real answer. It has two sentences."))
        self.assertFalse(
            is_usable_answer(
                "Adolf Hitler was the dictator of Germany from 1933 to 1945. His"
            )
        )

    def test_is_usable_answer_accepts_brief_factual_statement(self) -> None:
        self.assertTrue(is_usable_answer("Adolf Hitler was the dictator of Nazi Germany."))
        self.assertFalse(is_usable_answer("I do not know."))

    def test_overrelies_on_professional_care_rejects_unconditional_referral(self) -> None:
        answer = (
            "Clean the wound thoroughly and monitor for spreading redness. "
            "If you notice severe symptoms, you must seek medical attention immediately."
        )
        self.assertTrue(overrelies_on_professional_care(answer))
        self.assertFalse(is_usable_answer(answer))

    def test_overrelies_on_professional_care_rejects_immediate_medical_care_variant(self) -> None:
        answer = (
            "Clean the wound thoroughly and monitor for spreading redness. "
            "While you manage the wound at home, if you notice any of these signs, you must seek immediate medical care."
        )
        self.assertTrue(overrelies_on_professional_care(answer))
        self.assertFalse(is_usable_answer(answer))

    def test_overrelies_on_professional_care_allows_conditional_note(self) -> None:
        answer = (
            "Clean the wound thoroughly, flush out debris, and monitor for worsening redness or fever. "
            "If skilled medical help is available, get evaluation for a contaminated puncture wound."
        )
        self.assertFalse(overrelies_on_professional_care(answer))
        self.assertTrue(is_usable_answer(answer))

    def test_has_truncated_tail_detects_dangling_fragment(self) -> None:
        self.assertTrue(has_truncated_tail("Adolf Hitler was the dictator of Germany from 1933 to 1945. His"))
        self.assertFalse(has_truncated_tail("Adolf Hitler was the dictator of Germany from 1933 to 1945."))

    def test_trim_to_complete_sentences_removes_incomplete_tail(self) -> None:
        self.assertEqual(
            trim_to_complete_sentences("Adolf Hitler was the dictator of Germany from 1933 to 1945. His"),
            "Adolf Hitler was the dictator of Germany from 1933 to 1945.",
        )

    def test_ask_llama_retries_when_finish_reason_is_length(self) -> None:
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "Adolf Hitler was the dictator of Germany from 1933 to 1945. His"
                        },
                        "finish_reason": "length",
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Adolf Hitler was an Austrian-born German politician who led Nazi Germany from 1933 to 1945. "
                                "He was central to the rise of Nazism and the start of World War II."
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        ]

        with patch("src.cli.chat.http_json", side_effect=responses):
            answer = ask_llama(
                llama_url="http://localhost:8081",
                model_name="gemma-4-E4B-it-Q5_K_M",
                question="who was adolf hitler?",
                context="",
                history=[],
                max_tokens=384,
                timeout=60,
            )

        self.assertIn("Austrian-born German politician", answer)

    def test_ask_llama_records_raw_attempts_for_debug(self) -> None:
        responses = [
            {
                "choices": [
                    {
                        "message": {"content": "Too short."},
                        "finish_reason": "stop",
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Adolf Hitler was an Austrian-born German politician who led Nazi Germany from 1933 to 1945. "
                                "He was central to the rise of Nazism and the start of World War II."
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        ]
        attempts: list[dict] = []

        with patch("src.cli.chat.http_json", side_effect=responses):
            answer = ask_llama(
                llama_url="http://localhost:8081",
                model_name="gemma-4-E4B-it-Q5_K_M",
                question="who was adolf hitler?",
                context="",
                history=[],
                max_tokens=384,
                timeout=60,
                debug_attempts=attempts,
            )

        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["stage"], "initial")
        self.assertEqual(attempts[0]["answer"], "Too short.")
        self.assertEqual(attempts[0]["raw_answer"], "Too short.")
        self.assertEqual(attempts[1]["stage"], "retry")
        self.assertIn("Austrian-born German politician", answer)

    def test_ask_llama_disables_thinking_budget(self) -> None:
        captured_payloads: list[dict] = []

        def fake_http_json(method: str, url: str, payload: dict | None = None, timeout: int = 60) -> dict:
            assert payload is not None
            captured_payloads.append(payload)
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Adolf Hitler was an Austrian-born German politician who led Nazi Germany from 1933 to 1945. He was central to the rise of Nazism and the start of World War II."
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

        with patch("src.cli.chat.http_json", side_effect=fake_http_json):
            answer = ask_llama(
                llama_url="http://localhost:8081",
                model_name="gemma-4-E4B-it-Q5_K_M",
                question="who was adolf hitler?",
                context="",
                history=[],
                max_tokens=384,
                timeout=60,
            )

        self.assertIn("Austrian-born German politician", answer)
        self.assertEqual(captured_payloads[0]["thinking_budget_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
