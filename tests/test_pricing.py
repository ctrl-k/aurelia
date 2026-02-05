"""Tests for the pricing module."""

from __future__ import annotations

import pytest

from aurelia.core.pricing import DEFAULT_MODEL, GEMINI_PRICING, estimate_cost


class TestEstimateCost:
    """Tests for the estimate_cost function."""

    def test_estimate_cost_default_model(self):
        """Test cost estimation with default model."""
        # 1M input + 1M output with gemini-2.0-flash
        # Input: 1M * $0.075 / 1M = $0.075
        # Output: 1M * $0.30 / 1M = $0.30
        # Total: $0.375
        cost = estimate_cost(input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(0.375)

    def test_estimate_cost_zero_tokens(self):
        """Test cost estimation with zero tokens."""
        cost = estimate_cost(input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_estimate_cost_input_only(self):
        """Test cost with only input tokens."""
        # 100K input with gemini-2.0-flash
        # Input: 100K * $0.075 / 1M = $0.0075
        cost = estimate_cost(input_tokens=100_000, output_tokens=0)
        assert cost == pytest.approx(0.0075)

    def test_estimate_cost_output_only(self):
        """Test cost with only output tokens."""
        # 100K output with gemini-2.0-flash
        # Output: 100K * $0.30 / 1M = $0.03
        cost = estimate_cost(input_tokens=0, output_tokens=100_000)
        assert cost == pytest.approx(0.03)

    def test_estimate_cost_gemini_15_pro(self):
        """Test cost estimation with gemini-1.5-pro model."""
        # 1M input + 1M output with gemini-1.5-pro
        # Input: 1M * $1.25 / 1M = $1.25
        # Output: 1M * $5.00 / 1M = $5.00
        # Total: $6.25
        cost = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="gemini-1.5-pro",
        )
        assert cost == pytest.approx(6.25)

    def test_estimate_cost_unknown_model_uses_default(self):
        """Test that unknown model falls back to default pricing."""
        cost_unknown = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="unknown-model",
        )
        cost_default = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model=DEFAULT_MODEL,
        )
        assert cost_unknown == cost_default

    def test_estimate_cost_small_amounts(self):
        """Test cost estimation with typical usage amounts."""
        # 50K input, 10K output (typical coder task)
        # Input: 50K * $0.075 / 1M = $0.00375
        # Output: 10K * $0.30 / 1M = $0.003
        # Total: $0.00675
        cost = estimate_cost(input_tokens=50_000, output_tokens=10_000)
        assert cost == pytest.approx(0.00675)


class TestPricingData:
    """Tests for pricing data constants."""

    def test_default_model_exists_in_pricing(self):
        """Test that default model has pricing data."""
        assert DEFAULT_MODEL in GEMINI_PRICING

    def test_all_models_have_input_output_pricing(self):
        """Test that all models have input and output pricing."""
        for model, pricing in GEMINI_PRICING.items():
            assert "input" in pricing, f"Model {model} missing input pricing"
            assert "output" in pricing, f"Model {model} missing output pricing"

    def test_all_prices_are_positive(self):
        """Test that all prices are positive."""
        for model, pricing in GEMINI_PRICING.items():
            assert pricing["input"] > 0, f"Model {model} has non-positive input price"
            assert pricing["output"] > 0, f"Model {model} has non-positive output price"
