def opportunity_model(inputs):
    """
    Calculates a conservative annual commercial opportunity range.
    Defaults are applied when inputs are missing.
    """
    rooms = inputs.get("rooms")
    occupancy = inputs.get("occupancy")
    adr = inputs.get("adr")

    rooms = 60 if rooms is None else rooms
    occupancy = 0.72 if occupancy is None else occupancy
    adr = 140 if adr is None else adr

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


def render_report_md(payload):
    """
    Renders a consultant-grade report. Accepts:
    payload = {"scores": ..., "opportunity": ...}
    """
    scores = payload.get("scores", {}) or {}
    overall = scores.get("overall_score_0_to_100")

    layer_scores = scores.get("layer_scores")
    if layer_scores is None:
        layer_scores = []

    lines = []
    if isinstance(layer_scores, list):
        for item in layer_scores:
            if not isinstance(item, dict):
                continue
            name = item.get("layer") or item.get("name") or item.get("category") or "Layer"
            score = item.get("score") or item.get("value")
            maxv = item.get("max") or item.get("out_of") or item.get("maximum")
            if score is not None and maxv is not None:
                lines.append(f"• {name}: {score} / {maxv}")
            elif score is not None:
                lines.append(f"• {name}: {score}")
    if not lines:
        lines = ["• Score composition unavailable"]

    opp = payload.get("opportunity", {}) or {}
    low, high = (opp.get("annual_opportunity_gbp_range") or [0, 0])
    assumptions = opp.get("assumptions", {}) or {}
    rooms = assumptions.get("rooms", 60)
    occupancy = assumptions.get("occupancy", 0.72)
    adr = assumptions.get("adr", 140)

    try:
        occ_pct = float(occupancy) * 100
    except Exception:
        occ_pct = 72.0

    return f"""
# Hotel Technology & Revenue Readiness Assessment

## Executive Overview

**Technology Readiness Score:** {overall} / 100

**Score composition:**
{chr(10).join(lines)}

**Estimated Annual Opportunity:** £{int(low):,} – £{int(high):,}

This assessment provides a neutral, data-driven view of technology and commercial readiness, based on publicly observable digital signals, confirmed system inputs where provided, and conservative hospitality benchmarks.

---

## Commercial assumptions used

- Rooms: {rooms}
- Occupancy: {occ_pct:.0f}%
- ADR: £{adr}

Defaults are applied when inputs are not provided.

---

## Methodology & disclosures

- Public website and booking-journey signal analysis
- Confidence-scored detection and inference
- No access to private systems, data, or credentials
- Vendor-neutral and free from referral or commission bias
""".strip()
