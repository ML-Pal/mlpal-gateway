"""Tests for ImageSizeResolver, especially gpt-image-2 flexible resolutions.

gpt-image-2 accepts arbitrary sizes (each edge divisible by 16, longest edge
<= 3840, within OpenAI's pixel budget). The resolver must honor explicit pixel
sizes and true aspect ratios for it, while keeping the fixed-3-size behavior for
gpt-image-1/1.5 and DALL-E.
"""

import pytest

from mlpal_assistants_service.adapters.base import ImageSizeResolver as R


class TestFlexibleGptImage2:
    def test_explicit_pixels_pass_through(self):
        assert R.to_pixels_openai("2048x2048", model="gpt-image-2") == "2048x2048"
        assert R.to_pixels_openai("1792x1024", model="gpt-image-2") == "1792x1024"
        assert R.to_pixels_openai("1280x720", model="gpt-image-2") == "1280x720"

    def test_aligns_to_multiple_of_16(self):
        # 1080 is not divisible by 16; OpenAI requires it -> snap to 1088.
        assert R.to_pixels_openai("1920x1080", model="gpt-image-2") == "1920x1088"

    def test_caps_longest_edge_at_3840(self):
        # Over-large request scales down proportionally to the 3840 max edge
        # (OpenAI then enforces the pixel budget and returns a clean 400 if over).
        assert R.to_pixels_openai("4096x4096", model="gpt-image-2") == "3840x3840"

    def test_auto_passes_through(self):
        assert R.to_pixels_openai("auto", model="gpt-image-2") == "auto"

    def test_aspect_maps_to_true_ratio_not_clamped(self):
        # Real 16:9, not the legacy 3:2 clamp (1536x1024).
        assert R.to_pixels_openai("16:9", model="gpt-image-2") == "1536x864"
        assert R.to_pixels_openai("9:16", model="gpt-image-2") == "864x1536"
        assert R.to_pixels_openai("1:1", model="gpt-image-2") == "1024x1024"


class TestFixedModelsUnchanged:
    def test_gpt_image_1_still_clamps_to_three_sizes(self):
        # Flexibility must NOT leak to gpt-image-1 (only supports the fixed 3).
        assert R.to_pixels_openai("2048x2048", model="gpt-image-1") == "1024x1024"
        assert R.to_pixels_openai("1792x1024", model="gpt-image-1") == "1536x1024"
        assert R.to_pixels_openai("16:9", model="gpt-image-1") == "1536x1024"

    def test_gpt_image_1_5_still_clamps(self):
        assert R.to_pixels_openai("2048x2048", model="gpt-image-1.5") == "1024x1024"

    def test_dalle3_unchanged(self):
        assert R.to_pixels_openai("16:9", model="dall-e-3") == "1792x1024"
        assert R.to_pixels_openai("2048x2048", model="dall-e-3") == "1024x1024"


class TestHelpers:
    @pytest.mark.parametrize(
        "n,expected",
        [(1080, 1088), (1024, 1024), (720, 720), (1000, 992), (8, 16)],
    )
    def test_align_edge(self, n, expected):
        assert R._align_edge(n) == expected

    def test_parse_explicit_pixels(self):
        assert R._parse_explicit_pixels("2048x2048") == (2048, 2048)
        assert R._parse_explicit_pixels("16:9") is None
        assert R._parse_explicit_pixels("square") is None
