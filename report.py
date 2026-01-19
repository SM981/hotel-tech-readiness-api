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
        ],
        "primary_levers": [
            "Pricing accuracy and rate agility",
            "Direct mix and OTA cost control",
            "Repeat revenue via guest data automation",
            "Reduced manual reporting overhead"
        ],
        "scope_note": (
            "Conservative first-order impact only. Excludes longer-term guest lifetime value uplift, "
            "forecasting confidence benefits, and portfolio-scale compounding effects."
        )
    }


def _fmt_currency(value) -> str:
    try:
        return f"£{int(value):,}"
    except Exception:
        return "£0"


def _fmt_pct(value) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except Exception:
        return "72%"


def _safe_list(x):
    return x if isinstance(x, list) else []


def _score_composition_lines(scores: dict) -> list[str]:
    layer_scores = scores.get("layer_scores")
    lines = []

    for item in _safe_list(layer_scores):
        if not isinstance(item, dict):
            continue
        name = item.get("layer") or item.get("name") or item.get("category") or "Layer"
        score = item.get("score") if item.get("score") is not None else item.get("value")
        maxv = item.get("max") or item.get("out_of") or item.get("maximum")

        if score is not None and maxv is not None:
            lines.append(f"• {name}: {score} / {maxv}")
        elif score is not None:
            lines.append(f"• {name}: {score}")

    return lines or ["• Score composition unavailable"]


def _render_layers_md(layers: dict) -> str:
    """
    Renders MD-grade layer sections using:
    - visibility
    - detections
    - likely_state / typical_risk (when not visible)
    - strategic_importance + rationale
    """
    if not isinstance(layers, dict) or not layers:
        return "Layer breakdown unavailable."

    out = []
    idx = 1
    for layer_name, layer in layers.items():
        if not isinstance(layer, dict):
            continue

        visibility = layer.get("visibility", "Unknown")
        importance = layer.get("strategic_importance", "Medium")
        rationale = layer.get("importance_rationale", "")

        dets = _safe_list(layer.get("detections"))
        detected_str = ", ".join(
            f"{d.get('vendor','Unknown')} {d.get('product','')}".strip()
            for d in dets if isinstance(d, dict)
        ) or "None visible"

        likely_state = layer.get("likely_state")
        typical_risk = layer.get("typical_risk")

        out.append(f"## {idx}. {layer_name}")
        out.append(f"**Strategic importance:** {importance}")
        if rationale:
            out.append(f"*{rationale}*")
        out.append("")
        out.append(f"**Visibility:** {visibility}")
        out.append(f"**Detected tools:** {detected_str}")

        # When not visible, interpret rather than apologise
        if visibility != "Detected":
            if likely_state:
                out.append(f"**Likely state:** {likely_state}")
            if typical_risk:
                out.append(f"**Typical risk:** {typical_risk}")

        out.append("")
        out.append("**Next best step:**")
        # Provide consistent, practical next step per layer name
        out.append(_next_step_for_layer(layer_name))
        out.append("")
        idx += 1

    return "\n".join(out).strip()


def _next_step_for_layer(layer_name: str) -> str:
    # Tight, MD-friendly next steps (vendor-neutral)
    name = (layer_name or "").lower()

    if "distribution" in name:
        return (
            "Confirm booking engine/CRS and channel manager, then validate two-way rate & inventory sync, "
            "parity controls, and automated restrictions (min stay/CTA/CTD) across key channels."
        )
    if "core" in name or "pms" in name or "rms" in name:
        return (
            "Confirm PMS + RMS (or manual process). Assess whether pricing decisions are automated, "
            "centrally governed, and consistently deployed across properties."
        )
    if "guest" in name or "crm" in name:
        return (
            "Map guest data flows (web → booking → stay → post-stay). Identify the system of record for guest profiles "
            "and implement a single segmentation + consent model to power repeat/direct growth."
        )
    if "commercial" in name or "attribution" in name or "tracking" in name:
        return (
            "Run an attribution audit (GTM/GA4 + booking funnel events + paid media pixels). Ensure booking conversion "
            "events, value capture, and channel grouping are consistent across properties."
        )
    if "in-venue" in name or "experience" in name:
        return (
            "Identify the top 2–3 guest journey moments that drive satisfaction and spend (pre-arrival upsell, check-in, "
            "F&B ordering). Confirm integration points with PMS/POS."
        )
    if "operations" in name:
        return (
            "Confirm housekeeping/maintenance/task tools and validate integration with PMS room status. Target the "
            "highest-friction workflows first (room turns, out-of-order, engineering response)."
        )
    if "finance" in name or "reporting" in name:
        return (
            "Define 8–12 executive KPIs (RevPAR, GOPPAR, net ADR, direct share, CAC, repeat %, forecast accuracy). "
            "Build a single dashboard pulling from PMS/RMS/marketing sources with clear definitions."
        )
    return "Confirm current tools and integration depth, then prioritise one high-leverage improvement for the next 30 days."


def _render_roadmap_md(roadmap: dict) -> str:
    if not isinstance(roadmap, dict) or not roadmap:
        return "Roadmap unavailable."

    out = ["## 90-Day MD Agenda"]
    for phase, obj in roadmap.items():
        if not isinstance(obj, dict):
            continue
        outcome = obj.get("outcome")
        exec_q = obj.get("exec_question")
        out.append(f"### {phase}")
        if outcome:
            out.append(f"**Outcome:** {outcome}")
        if exec_q:
            out.append(f"**Exec question:** {exec_q}")
        out.append("")
    return "\n".join(out).strip()


def render_report_md(payload):
    """
    MD-grade report renderer.

    Supports two inputs:
    1) Full analysis dict from API:
       payload = {
         "url":..., "scores":..., "benchmarks":..., "layers":..., "roadmap":..., "opportunity":...
       }

    2) Backwards-compatible minimal dict:
       payload = {"scores":..., "opportunity":...}
    """
    payload = payload or {}

    scores = payload.get("scores", {}) or {}
    overall = scores.get("overall_score_0_to_100")

    # Benchmarks (optional)
    benchmarks = payload.get("benchmarks", {}) or {}
    typical_range = benchmarks.get("typical_range")
    best_in_class = benchmarks.get("best_in_class")
    interpretation = benchmarks.get("interpretation")

    # Opportunity
    opp = payload.get("opportunity", {}) or {}
    low, high = (opp.get("annual_opportunity_gbp_range") or [0, 0])
    assumptions = opp.get("assumptions", {}) or {}
    rooms = assumptions.get("rooms", 60)
    occupancy = assumptions.get("occupancy", 0.72)
    adr = assumptions.get("adr", 140)
    levers = _safe_list(opp.get("primary_levers"))
    scope_note = opp.get("scope_note")

    # Layers + roadmap (optional, MD-grade)
    layers = payload.get("layers", {})
    roadmap = payload.get("roadmap", {})

    score_lines = _score_composition_lines(scores)

    bench_line = ""
    if isinstance(typical_range, (list, tuple)) and len(typical_range) == 2:
        bench_line = f"**Peer context:** Typical range {typical_range[0]}–{typical_range[1]} (best-in-class {best_in_class}+)"
    elif best_in_class is not None:
        bench_line = f"**Peer context:** Best-in-class {best_in_class}+"

    interp_line = f"**Interpretation:** {interpretation}" if interpretation else ""

    # Build levers text
    levers_md = ""
    if levers:
        levers_md = "\n".join([f"- {x}" for x in levers])

    scope_md = f"*{scope_note}*" if scope_note else ""

    layers_md = _render_layers_md(layers) if layers else ""
    roadmap_md = _render_roadmap_md(roadmap) if roadmap else ""

    return f"""
# Hotel Technology & Revenue Readiness Assessment

## Executive Overview

**Technology Readiness Score:** {overall} / 100  
{bench_line}
{interp_line}

**Score composition:**
{chr(10).join(score_lines)}

**Estimated Annual Opportunity:** {_fmt_currency(low)} – {_fmt_currency(high)}  
{scope_md}

### What this means (MD view)
This assessment highlights where system connectivity and commercial automation are likely to be constraining decision speed, pricing accuracy, and repeat/direct growth. Where systems are not publicly visible, the focus is on integration risk and optimisation potential rather than tool presence.

---

## Commercial assumptions used

- Rooms: {rooms}
- Occupancy: {_fmt_pct(occupancy)}
- ADR: £{adr}

Defaults are applied when inputs are not provided.

---

## Primary value levers
{levers_md if levers_md else "- Pricing and channel optimisation\n- Direct mix and margin control\n- Guest data automation\n- Reduced manual reporting overhead"}

---

{roadmap_md if roadmap_md else ""}

---

{layers_md if layers_md else ""}

---

## Methodology & disclosures
- Public website and booking-journey signal analysis (where accessible)
- Confidence-scored detection and structured inference when signals are not visible
- No access to private systems, credentials, or guest data
- Vendor-neutral and free from referral or commission bias
""".strip()
