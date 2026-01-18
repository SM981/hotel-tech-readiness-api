def opportunity_model(inputs):
    rooms = inputs.get("rooms", 60)
    occupancy = inputs.get("occupancy", 0.72)
    adr = inputs.get("adr", 140)

    room_revenue = rooms * 365 * occupancy * adr

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
