def interpret_score(score: float | None, benchmark: dict) -> str:
    if score is None:
        return "Score unavailable due to limited public signals."

    low, high = benchmark["typical_range"]

    if score < low:
        return "Below typical range — suggests fragmented integration rather than lack of systems."
    if score <= high:
        return "Within typical range — indicates solid foundations with optimisation opportunity."
    return "Above typical range — indicates strong integration and automation."
