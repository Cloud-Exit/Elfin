"""
Unit tests for Slice 5: multimodal vision CLI.
"""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.cli.vision import (
    analyze_image,
    base64_image,
    check_services,
    extract_visible_answer,
    is_image_specific_enough,
    is_usable_answer,
)


class VisionBase64Tests(unittest.TestCase):
    def test_base64_image_png(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.flush()
            path = Path(f.name)

        encoded, mime = base64_image(path)
        self.assertEqual(mime, "image/png")
        self.assertEqual(base64.b64decode(encoded), b"\x89PNG\r\n\x1a\n")
        path.unlink()

    def test_base64_image_jpg(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff")
            f.flush()
            path = Path(f.name)

        encoded, mime = base64_image(path)
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual(base64.b64decode(encoded), b"\xff\xd8\xff")
        path.unlink()

    def test_base64_image_webp(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            f.write(b"RIFF....WEBP")
            f.flush()
            path = Path(f.name)

        encoded, mime = base64_image(path)
        self.assertEqual(mime, "image/webp")
        path.unlink()

    def test_base64_image_unsupported_ext_defaults_png(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
            f.write(b"rawimage")
            f.flush()
            path = Path(f.name)

        encoded, mime = base64_image(path)
        self.assertEqual(mime, "image/png")
        path.unlink()

    def test_check_services_ok(self) -> None:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("src.cli.vision.urllib.request.urlopen", return_value=mock_response):
            errors = check_services("http://localhost:8081")
        self.assertEqual(errors, [])

    def test_check_services_unreachable(self) -> None:
        import urllib.error

        with patch("src.cli.vision.urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            errors = check_services("http://localhost:8081")
        self.assertEqual(len(errors), 1)
        self.assertIn("unreachable", errors[0].lower())

    def test_check_services_non_200(self) -> None:
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("src.cli.vision.urllib.request.urlopen", return_value=mock_response):
            errors = check_services("http://localhost:8081")
        self.assertEqual(len(errors), 1)
        self.assertIn("500", errors[0])


class VisionAnalysisTests(unittest.TestCase):
    def test_analyze_image_missing_file(self) -> None:
        result, finish_reason, errors = analyze_image(
            llama_url="http://localhost:8081",
            model="gemma-4-E4B-it-Q5_K_M",
            image_path="/nonexistent/image.png",
            prompt="test",
            max_tokens=512,
            timeout=30,
        )
        self.assertEqual(result, "")
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0])

    def test_analyze_image_empty_response(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.flush()
            test_image = f.name

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b'{"choices": [{"message": {"content": ""}}]}'

        with patch("src.cli.vision.urllib.request.urlopen", return_value=mock_response):
            result, finish_reason, errors = analyze_image(
                llama_url="http://localhost:8081",
                model="gemma-4-E4B-it-Q5_K_M",
                image_path=test_image,
                prompt="test",
                max_tokens=512,
                timeout=30,
            )
        self.assertEqual(result, "")
        self.assertIn("empty response", errors[0])
        Path(test_image).unlink()

    def test_analyze_image_no_choices(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.flush()
            test_image = f.name

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b'{"choices": []}'

        with patch("src.cli.vision.urllib.request.urlopen", return_value=mock_response):
            result, finish_reason, errors = analyze_image(
                llama_url="http://localhost:8081",
                model="gemma-4-E4B-it-Q5_K_M",
                image_path=test_image,
                prompt="test",
                max_tokens=512,
                timeout=30,
            )
        self.assertEqual(result, "")
        self.assertIn("no choices", errors[0])
        Path(test_image).unlink()

    def test_analyze_image_reasoning_only_rejected(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.flush()
            test_image = f.name

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = (
            json.dumps({
                "choices": [{
                    "message": {"content": "I can't inspect images directly"},
                    "finish_reason": "stop",
                }],
            })
            .encode()
        )

        with patch("src.cli.vision.urllib.request.urlopen", return_value=mock_response):
            result, finish_reason, errors = analyze_image(
                llama_url="http://localhost:8081",
                model="gemma-4-E4B-it-Q5_K_M",
                image_path=test_image,
                prompt="test",
                max_tokens=512,
                timeout=30,
            )
        # analyze_image returns content text + empty errors; the quality gate is in main()
        # but the content_text should contain the rejection marker
        self.assertIn("can't inspect", result.lower())
        Path(test_image).unlink()

    def test_analyze_image_success(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.flush()
            test_image = f.name

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = (
            json.dumps({
                "choices": [{
                    "message": {"content": "The image shows a field with some green vegetation."},
                    "finish_reason": "stop",
                }],
            })
            .encode()
        )

        with patch("src.cli.vision.urllib.request.urlopen", return_value=mock_response):
            result, finish_reason, errors = analyze_image(
                llama_url="http://localhost:8081",
                model="gemma-4-E4B-it-Q5_K_M",
                image_path=test_image,
                prompt="test",
                max_tokens=512,
                timeout=30,
            )
        self.assertEqual(errors, [])
        self.assertEqual(finish_reason, "stop")
        self.assertIn("green vegetation", result.lower())
        Path(test_image).unlink()

    def test_analyze_image_truncated_returns_finish_reason(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.flush()
            test_image = f.name

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = (
            json.dumps({
                "choices": [{
                    "message": {"content": "The image shows a field with some green vegetation that"},
                    "finish_reason": "length",
                }],
            })
            .encode()
        )

        with patch("src.cli.vision.urllib.request.urlopen", return_value=mock_response):
            result, finish_reason, errors = analyze_image(
                llama_url="http://localhost:8081",
                model="gemma-4-E4B-it-Q5_K_M",
                image_path=test_image,
                prompt="test",
                max_tokens=512,
                timeout=30,
            )
        self.assertEqual(finish_reason, "length")
        self.assertIn("truncated", errors[0])
        Path(test_image).unlink()

    def test_analyze_image_payload_shape(self) -> None:
        """Verify the outbound chat payload has the correct multimodal structure."""

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.flush()
            test_image = f.name

        captured_url = []
        captured_body = []

        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b'{"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}'

        def capture_request(req, *args, **kwargs):
            captured_url.append(req.full_url)
            captured_body.append(req.data)
            return FakeResponse()

        with patch("src.cli.vision.urllib.request.urlopen", side_effect=capture_request):
            try:
                analyze_image(
                    llama_url="http://localhost:8081",
                    model="gemma-4-E4B-it-Q5_K_M",
                    image_path=test_image,
                    prompt="describe this",
                    max_tokens=512,
                    timeout=30,
                )
            except Exception:
                pass

        self.assertEqual(len(captured_url), 1)
        self.assertIn("/v1/chat/completions", captured_url[0])
        self.assertEqual(len(captured_body), 1)
        payload = json.loads(captured_body[0])
        messages = payload.get("messages")
        self.assertIsNotNone(messages)
        # Should have system + user messages
        self.assertGreaterEqual(len(messages), 2)
        # User message should contain image_url content block
        user_msg = messages[-1]
        user_content = user_msg.get("content")
        self.assertIsInstance(user_content, list)
        self.assertTrue(any(
            block.get("type") == "image_url"
            for block in user_content
        ))
        # Must include thinking_budget_tokens=0
        self.assertEqual(payload.get("thinking_budget_tokens"), 0)

        Path(test_image).unlink()


class VisionQualityGateTests(unittest.TestCase):
    def test_usable_answer_normal_text(self) -> None:
        self.assertTrue(is_usable_answer("The image shows a person standing in a field."))

    def test_usable_answer_ending_with_period(self) -> None:
        self.assertTrue(is_usable_answer("A red barn stands in a green field."))

    def test_usable_answer_rejects_generic_prose_without_visual_detail(self) -> None:
        self.assertFalse(is_usable_answer("This is a complete sentence."))
        self.assertFalse(is_usable_answer("There is something visible here."))
        self.assertFalse(is_usable_answer("It appears to be an image."))

    def test_usable_answer_reasoning_marker(self) -> None:
        self.assertFalse(is_usable_answer("I cannot view images directly"))
        self.assertFalse(is_usable_answer("I'm unable to analyze this image"))
        self.assertFalse(is_usable_answer("I can't inspect images"))
        self.assertFalse(is_usable_answer("I don't support image input"))
        self.assertFalse(is_usable_answer("This is a text-only interface"))

    def test_usable_answer_truncated_mid_word(self) -> None:
        self.assertFalse(is_usable_answer("The image shows a field with some green vegetation th"))

    def test_usable_answer_truncated_complete_sentence(self) -> None:
        # "vegetation. The" — dangling tail after complete sentence is truncated
        self.assertFalse(is_usable_answer("The image shows a field with some green vegetation. The"))

    def test_usable_answer_empty_string(self) -> None:
        self.assertFalse(is_usable_answer(""))

    def test_extract_visible_answer_strips_thinking(self) -> None:
        # The function now strips the entire reasoning block (label + body).
        result = extract_visible_answer("thinking process:\nlet me think about this\n\nThe image shows a field.")
        self.assertIn("The image shows a field", result)
        self.assertNotIn("let me think", result)

    def test_extract_visible_answer_strips_plan(self) -> None:
        result = extract_visible_answer("plan: 1. look at image\n\nThe image shows a field.")
        self.assertIn("The image shows a field", result)
        self.assertNotIn("plan:", result)

    def test_extract_visible_answer_strips_channel_marker(self) -> None:
        result = extract_visible_answer("thinking here<channel|>Actual answer here")
        self.assertEqual(result, "Actual answer here")


class VisionImageSpecificityTests(unittest.TestCase):
    def test_image_specific_with_color(self) -> None:
        self.assertTrue(is_image_specific_enough("The image shows a red barn next to a wooden fence."))

    def test_image_specific_with_terrain(self) -> None:
        self.assertTrue(is_image_specific_enough("A person is standing on a steep hillside."))

    def test_image_specific_with_action(self) -> None:
        self.assertTrue(is_image_specific_enough("Someone is holding a metal tool in their hand."))

    def test_image_specific_with_weather(self) -> None:
        self.assertTrue(is_image_specific_enough("There is rain and strong wind visible."))

    def test_image_specific_generic_short_rejected(self) -> None:
        self.assertFalse(is_image_specific_enough("The image shows an object in a place."))
        self.assertFalse(is_image_specific_enough("The image appears to be something interesting."))

    def test_image_specific_short_generic_fails(self) -> None:
        self.assertFalse(is_image_specific_enough("I see something in the picture."))
        self.assertFalse(is_image_specific_enough("The image shows an object."))

    def test_image_specific_short_specific_passes(self) -> None:
        self.assertTrue(is_image_specific_enough("A blue sky with clouds."))

    def test_is_usable_rejects_non_image_specific(self) -> None:
        # Generic text that passes punctation check should still fail image specificity
        self.assertFalse(is_usable_answer("This is a definition of a term. It explains the concept fully and completely."))
