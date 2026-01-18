def render_report_md(analysis):
    """
    Renders a consultant-grade readiness report with transparent scoring,
    opportunity context, and clear disclosures — without crashing if score
    structures differ.
    """
    scores = analysis.get("scores", {}) or {}
    overall = scores.get("overall_score_0_to_100")

    # layer_scores can vary by implementation; handle list or dict safely
    layer_scores = scores.get("layer_scores")
    if layer_scores is None:
        layer_scores = scores.get("layers")  # alternate naming
    if layer_scores is None:
        layer_scores = []

    layers_lines = []

    # Case A: list of dicts
    if isinstance(layer_scores, list):
        for item in layer_scores:
            if not isinstance(item, dict):
                continue
            name = item.get("layer") or item.get("name") or item.get("category") or "Layer"
            score = item.get("score") or item.get("value")
            maxv = item.get("max") or item.get("out_of") or item.get("maximum")
            if score is not None and maxv is not None:
                layers_lines.append(f"• {name}: {score} / {maxv}")
            elif score is not None:
                layers_lines.append(f"• {name}: {score}")

    # Case B: dict of layers
    elif isinstance(layer_scores, dict):
        for name, val in layer_scores.items():
            if isinstance(val, dict):
                score = val.get("score") or val.get("value")
                maxv = val.get("max") or val.get("out_of") or val.get("maximum")
                if score is not None and maxv is not None:
                    layers_lines.append(f"• {name}: {score} / {maxv}")
                elif score is not None:
                    layers_lines.append(f"• {name}: {score}")
            else:
                # plain number
                layers_lines.append(f"• {name}: {val}")

    if not layers_lines:
        layers_lines = ["• Score composition unavailable (confirm core systems to improve accuracy)"]

    opp = analysis.get("opportunity", {}) or {}
    rng = opp.get("annual_opportunity_gbp_range") or [0, 0]
    low, high = rng[0], rng[1]

    assumptions = opp.get("assumptions", {}) or {}
    rooms = assumptions.get("rooms", 60)
    occupancy = assumptions.get("occupancy", 0.72)
    adr = assumptions.get("adr", 140)

    # Safe formatting
    try:
        occ_pct = float(occupancy) * 100
    except Exception:
        occ_pct = 72.0

    return f"""
# Hotel Technology & Revenue Readiness Assessment

## Executive Overview

**Technology Readiness Score:** {overall} / 100

**Score composition:**
{chr(10).join(layers_lines)}

**Estimated Annual Opportunity:** £{int(low):,} – £{int(high):,}

This assessment provides a neutral, data-driven view of technology and commercial readiness, based on publicly observable digital signals, confirmed system inputs where provided, and conservative hospitality benchmarks.

---

## How to interpret this score

- The readiness score reflects **system connectivity and maturity**, not operational performance.
- Some hotel systems (e.g. PMS, RMS, finance, operations) do **not expose public web signals** and may appear as *Not publicly visible* unless confirmed.
- Opportunity ranges illustrate **order-of-magnitude potential**, not guaranteed outcomes.

---

## Commercial assumptions used

- Rooms: {rooms}
- Occupancy: {occ_pct:.0f}%
- ADR: £{adr}

Defaults are applied when inputs are not provided to avoid overstating impact.

---

## Methodology & disclosures

- Public website and booking-journey signal analysis
- Confidence-scored detection and inference
- No access to private systems, data, or credentials
- Vendor-neutral and free from referral or commission bias

Confirming one or two internal systems (e.g. booking engine, CRM, RMS) typically increases score accuracy and sharpens the commercial recommendations.
""".strip()
