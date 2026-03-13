"""Model pricing in USD per million tokens."""

# (input_per_Mtok, output_per_Mtok, cache_write_per_Mtok, cache_read_per_Mtok)
PRICING: dict[str, tuple[float, float, float, float]] = {
    # Claude 4 family
    "claude-opus-4-5":              (15.00, 75.00,  18.75, 1.50),
    "claude-opus-4-20250514":       (15.00, 75.00,  18.75, 1.50),
    "claude-sonnet-4-5":            (3.00,  15.00,  3.75,  0.30),
    "claude-sonnet-4-20250514":     (3.00,  15.00,  3.75,  0.30),
    "claude-haiku-4-5":             (0.80,  4.00,   1.00,  0.08),
    "claude-haiku-4-5-20251001":    (0.80,  4.00,   1.00,  0.08),
    # Claude 3.7
    "claude-sonnet-3-7":            (3.00,  15.00,  3.75,  0.30),
    "claude-sonnet-3-7-20250219":   (3.00,  15.00,  3.75,  0.30),
    # Claude 3.5
    "claude-opus-3-5":              (15.00, 75.00,  18.75, 1.50),
    "claude-sonnet-3-5":            (3.00,  15.00,  3.75,  0.30),
    "claude-sonnet-3-5-20241022":   (3.00,  15.00,  3.75,  0.30),
    "claude-haiku-3-5":             (0.80,  4.00,   1.00,  0.08),
    "claude-haiku-3-5-20241022":    (0.80,  4.00,   1.00,  0.08),
    # Claude 3
    "claude-opus-3-20240229":       (15.00, 75.00,  18.75, 1.50),
    "claude-sonnet-3-20240229":     (3.00,  15.00,  3.75,  0.30),
    "claude-haiku-3-20240307":      (0.25,  1.25,   0.30,  0.03),
    # OpenAI / Codex
    "gpt-4o":                       (2.50,  10.00,  0.00,  1.25),
    "gpt-4o-mini":                  (0.15,  0.60,   0.00,  0.075),
    "gpt-4.1":                      (2.00,  8.00,   0.00,  0.50),
    "gpt-4.1-mini":                 (0.40,  1.60,   0.00,  0.10),
    "gpt-4.1-nano":                 (0.10,  0.40,   0.00,  0.025),
    "o3":                           (10.00, 40.00,  0.00,  2.50),
    "o4-mini":                      (1.10,  4.40,   0.00,  0.275),
    "codex-davinci-002":            (2.00,  2.00,   0.00,  0.00),
    # Gemini
    "gemini-2.5-pro":               (1.25,  10.00,  0.00,  0.31),
    "gemini-2.5-flash":             (0.075, 0.30,   0.00,  0.019),
    "gemini-2.0-flash":             (0.10,  0.40,   0.00,  0.025),
}

def get_price(model: str) -> tuple[float, float, float, float]:
    """Return pricing for a model. Falls back to fuzzy prefix matching."""
    if model in PRICING:
        return PRICING[model]
    # fuzzy match: find longest prefix
    model_lower = model.lower()
    best = None
    best_len = 0
    for key in PRICING:
        if model_lower.startswith(key.lower()) or key.lower().startswith(model_lower.split("-20")[0].lower()):
            if len(key) > best_len:
                best = key
                best_len = len(key)
    if best:
        return PRICING[best]
    # default fallback
    return (3.00, 15.00, 3.75, 0.30)

def calc_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Calculate cost in USD for a given usage."""
    inp, out, cw, cr = get_price(model)
    return (
        input_tokens * inp / 1_000_000
        + output_tokens * out / 1_000_000
        + cache_write_tokens * cw / 1_000_000
        + cache_read_tokens * cr / 1_000_000
    )
