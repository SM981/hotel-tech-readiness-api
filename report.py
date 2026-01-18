def opportunity_model(inputs):
    """
    Calculates a conservative annual commercial opportunity range based on
    rooms, occupancy, and ADR. Defaults are applied when inputs are missing.
    """
    rooms = inputs.get("rooms")
    occupancy = inputs.get("occupancy")
    adr = inputs.get("adr")

    # Sensible defaults when values are not provided
    rooms = 60 if rooms is None else rooms
    occupancy = 0.72 if occupancy is None else occupancy
    adr = 140 if adr is None else adr

    room_revenue = rooms * 365 * occupancy * adr

    # Conservative improvement range from tech + commercial maturity uplift
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
    """
    Renders a consultant-grade readiness report with transparent scoring,
    opportunity context, and clear disclosures.
    """
    scores = analysis["scores"]
    overall = scores.get("overall_score_0_to_100")
    layers = scores.get("layer_scores", [])

    opp = analysis["opportunity"]
    low, high = opp["annual_opportunity_gbp_range"]
    assumptions = opp["assumptions"]

    # Build score composition lines
    if layers:
        layer_lines = "\n".join(
            f"• {l['layer']}: {l['score']} / {l['max']}"
            for l in layers
        )
    else:
        layer_lines = "• Score composition unavailable"

    return f"""
# Hotel Technology & Revenue Readiness Assessment

## Executive Overview

**Technology Readiness Score:** {overall} / 100

**Score composition:**
{layer_lines}

**Estimated Annual Opportunity:** £{int(low):,} – £{int(high):,}

This assessment provides a neutral, data-driven view of technology and commercial readiness, based on publicly observable digital signals, confirmed system inputs where provided, and conservative hospitality benchmarks.

---

## How to interpret this score

- The readiness score reflects **system connectivity and maturity**, not operational performance.
- Some hotel systems (e.g. PMS, RMS, finance, operations) do **not expose public web signals** and may appear as *Not publicly visible* unless confirmed.
- Opportunity ranges illustrate **order-of-magnitude potential**, not guaranteed outcomes.

---

## Commercial assumptions used

- Rooms: {assumptions['rooms']}
- Occupancy: {assumptions['occupancy'] * 100:.0f}%
- ADR: £{assumptions['adr']}

Defaults are applied when inputs are not provided to avoid overstating impact.

---

## Methodology & disclosures

- Public website and booking-journey signal analysis
- Confidence-scored detection and inference
- No access to private systems, data, or credentials
- Vendor-neutral and free from referral or commission bias

Confirming one or two internal systems (e.g. booking engine, CRM, RMS) typically increases score accuracy and sharpens the commercial recommendations.
""".strip()
