def opportunity_model(inputs):
    # Use sensible defaults when values are missing / None
    rooms = inputs.get("rooms")
    occupancy = inputs.get("occupancy")
    adr = inputs.get("adr")

    rooms = 60 if rooms is None else rooms
    occupancy = 0.72 if occupancy is None else occupancy
    adr = 140 if adr is None else adr

    room_revenue = rooms * 365 * occupancy * adr

    # Conservative improvement range for tech + commercial maturity uplift
    low = room_revenue * 0.013
    high = room_revenue * 0.05

    return {
        "assumptions": {
            "rooms": rooms,
            "occupancy": occupancy,
            "adr": adr
        },
        "annual_opportunity_gbp_range": [
            round(low, 0),
            round(high, 0)
        ]
    }


def render_report_md(analysis):
    score = analysis["scores"]["overall_score_0_to_100"]
    low, high = analysis["opportunity"]["annual_opportunity_gbp_range"]

    return f"""
# Hotel Technology & Revenue Readiness Report

**Technology Readiness Score:** {score}/100  
**Estimated Annual Opportunity:** £{int(low):,} – £{int(high):,}

This assessment is based on publicly observable digital signals and conservative hospitality benchmarks.

## Methodology
- Public booking journey and script analysis
- Confidence-scored detection
- No access to private systems

Results should be verified to improve accuracy.
""".strip()
