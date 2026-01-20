"""
Hotel Tech Readiness — report helpers
This module MUST export:
- opportunity_model
- render_report_md
"""

def opportunity_model(inputs):
    """
    Conservative annual commercial opportunity model.
    Defaults applied when inputs are missing.
    """
    inputs = inputs or {}
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
        "assumptions": {"rooms": rooms, "occupancy": occupancy, "adr": adr},
        "annual_opportunity_gbp_range": [round(low, 0), round(high, 0)],
        "scope_note": (
            "Indicative first-order impact only. Excludes longer-term LTV, "
            "portfolio effects, and multi-year compounding."
        ),
    }


def render_report_md(payload):
    """
    Minimal safe renderer to keep API stable.
    You can replace this with your MD-grade version once deploy is green.
    """
    payload = payload or {}
    url = payload.get("url", "")
    scores = payload.get("scores", {}) or {}
    opp = payload.get("opportunity", {}) or {}
    overall = scores.get("overall_score_0_to_100")

    rng = opp.get("annual_opportunity_gbp_range", [0, 0])
    low, high = (rng + [0, 0])[:2]

    return (
        "# Hotel Technology & Revenue Readiness Assessment\n\n"
        f"**Property reviewed:** {url}\n\n"
        f"**Technology Readiness Score:** {overall} / 100\n\n"
        f"**Indicative annual opportunity:** £{int(low):,} – £{int(high):,}\n"
    )
