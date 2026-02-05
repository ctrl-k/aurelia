"""LLM pricing information for cost estimation."""

from __future__ import annotations

# Gemini pricing (per 1M tokens) - as of Feb 2026
# https://ai.google.dev/pricing
GEMINI_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.0-flash": {
        "input": 0.075,  # $0.075 per 1M input tokens
        "output": 0.30,  # $0.30 per 1M output tokens
    },
    "gemini-2.0-flash-lite": {
        "input": 0.02,
        "output": 0.08,
    },
    "gemini-1.5-pro": {
        "input": 1.25,
        "output": 5.00,
    },
    "gemini-1.5-flash": {
        "input": 0.075,
        "output": 0.30,
    },
}

# Default model when not specified
DEFAULT_MODEL = "gemini-2.0-flash"


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = DEFAULT_MODEL,
) -> float:
    """Estimate cost in USD for token usage.

    Args:
        input_tokens: Number of input tokens used.
        output_tokens: Number of output tokens generated.
        model: The model name. Defaults to gemini-2.0-flash.

    Returns:
        Estimated cost in USD.
    """
    pricing = GEMINI_PRICING.get(model, GEMINI_PRICING[DEFAULT_MODEL])
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost
