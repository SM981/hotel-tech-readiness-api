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


# ==========================
# Tool landscape (vendor-neutral examples)
# ==========================
TOOL_LANDSCAPE = {
    "Distribution": {
        "Booking engine / CRS": [
            "SiteMinder", "Sabre SynXis", "D-EDGE", "Cloudbeds", "Avvio", "TravelClick"
        ],
        "Channel manager": [
            "SiteMinder", "D-EDGE", "RateGain", "DerbySoft", "STAAH"
        ],
        "Rate shopping / parity": [
            "OTA Insight", "Lighthouse"
        ],
    },
    "Core Systems": {
        "PMS": [
            "Oracle OPERA", "Guestline", "Mews", "protel", "Stayntouch", "Cloudbeds"
        ],
        "RMS (dynamic pricing)": [
            "Duetto", "Atomize", "IDeaS", "Pace", "FLYR Hospitality"
        ],
        "Integration / marketplace": [
            "HAPI", "Mews Marketplace", "Oracle OHIP (where available)"
        ],
    },
    "Guest Data & CRM": {
        "CRM / CDP / guest profile": [
            "Revinate", "Cendyn", "Salesforce", "Microsoft Dynamics", "HubSpot"
        ],
        "Email / lifecycle automation": [
            "Revinate", "Cendyn", "Mailchimp", "Klaviyo"
        ],
        "Reputation / guest feedback": [
            "ReviewPro", "TrustYou", "Medallia"
        ],
    },
    "Commercial Execution": {
        "Analytics & attribution": [
            "GA4", "Looker Studio", "Adobe Analytics", "Matomo"
        ],
        "Tag governance": [
            "Google Tag Manager"
        ],
        "Metasearch": [
            "Google Hotel Ads", "Tripadvisor", "Trivago"
        ],
        "Conversion rate optimisation": [
            "Hotjar", "Microsoft Clarity", "VWO", "Optimizely"
        ],
    },
    "In-Venue Experience": {
        "Guest messaging": [
            "HelloShift", "ALICE", "Akia", "Whistle"
        ],
        "Digital check-in / keys": [
            "AeroGuest", "Duve", "Virdee", "SALTO", "Assa Abloy"
        ],
        "Upsells / pre-arrival": [
            "Oaky", "Duve"
        ],
        "Digital compendium": [
            "Canary", "Duve"
        ],
    },
    "Operations": {
        "Housekeeping / tasks": [
            "Flexkeeping", "Optii", "HotSOS", "ALICE", "RoomChecking"
        ],
        "Maintenance / engineering": [
            "HotSOS", "UpKeep", "Hippo CMMS"
        ],
        "Staff comms / scheduling": [
            "Shyft", "Deputy", "When I Work"
        ],
    },
    "Finance & Reporting": {
        "Hotel BI / benchmarking": [
            "HotStats", "Lighthouse", "OTA Insight"
        ],
        "General BI": [
            "Power BI", "Looker Studio", "Tableau"
        ],
        "Accounting": [
            "Xero", "Sage", "QuickBooks"
        ],
        "Data aggregation": [
            "Fivetran", "Stitch", "Segment"
        ],
    },
}

_TOOL_NOTES = (
    "*Examples are illustrative and vendor-neutral. Fit depends on governance (group vs property), "
    "integration landscape, budget, and operational constraints.*"
)


def _render_tools_for_layer(layer_name: str, layer: dict) -> str:
    """
    Renders a neutral 'Common tools used...' section.
    Only shows when there is a gap or low visibility for that layer.
    """
    if not layer_name:
        return ""

    visibility = (layer or {}).get("visibility", "Unknown")
    dets = _safe_list((layer or {}).get("detections"))

    # Show when not publicly visible OR no detections.
    show = (visibility != "Detected") or (len(dets) == 0)
    if not show:
        return ""

    landscape = TOOL_LANDSCAPE.get(layer_name)
    if not isinstance(landscape, dict) or not landscape:
        return ""

    out = []
    out.append("**Common tools used by comparable hotels:**")
    out.append("Hotels of a similar size and positioning typically address this gap using tools in these categories:")

    for category, vendors in landscape.items():
        if not vendors:
            continue
        short = vendors[:5]  # keep short to avoid vendor-directory vibe
        out.append(f"- **{category}:** " + ", ".join(short))

    out.append("")
    out.append(_TOOL_NOTES)

    return "\n".join(out).strip()


def _render_tools_shortlist_md(layers: dict) -> str:
    """
    Consolidated tool shortlist only for layers that are not publicly visible.
    Keeps the report punchy while still adding value.
    """
    if not isinstance(layers, dict) or not layers:
        return ""

    preferred_order = [
        "Distribution",
        "Core Systems",
        "Guest Data & CRM",
        "Commercial Execution",
        "In-Venue Experience",
        "Operations",
        "Finance & Reporting",
    ]

    lines = ["## Tool landscape (examples by gap)"]
    any_added = False

    for layer_name in preferred_order:
        layer = layers.get(layer_name)
        if not isinstance(layer, dict):
            continue

        visibility = layer.get("visibility", "Unknown")
        dets = _safe_list(layer.get("detections"))

        if visibility == "Detected" and dets:
            continue

        landscape = TOOL_LANDSCAPE.get(layer_name)
        if not landscape:
            continue

        any_added = True
        lines.append(f"### {layer_name}")
        for category, vendors in landscape.items():
            if vendors:
                lines.append(f"- **{category}:** " + ", ".join(vendors[:5]))
        lines.append("")

    if not any_added:
        return ""

    lines.append(_TOOL_NOTES)
    return "\n".join(lines).strip()


def _render_layers_md(layers: dict) -> str:
    """
    Renders MD-grade layer sections using:
    - visibility
    - detections
    - likely_state / typical_risk (when not visible)
    - strategic_importance + rationale
    - common tools used by comparable hotels (vendor-neutral examples)
    """
    if not isinstance(layers, dict) or not layers:
        return "Layer breakdown unavailable."

    out = []
    idx = 1

    preferred_order = [
        "Distribution",
        "Core Systems",
        "Guest Data & CRM",
        "Commercial Execution",
        "In-Venue Experience",
        "Operations",
        "Finance & Reporting",
    ]
    ordered_keys = [k for k in preferred_order if k in layers] + [k for k in layers.keys() if k not in preferred_order]

    for layer_name in ordered_keys:
        layer = layers.get(layer_name)
        if not isinstance(layer, dict):
            continue

        visibility = layer.get("visibility", "Unknown")
        importance = layer.get("strategic_importance", "Medium")
        rationale = layer.get("importance_rationale", "")

        dets = _safe_list(layer.get("detections"))

        if dets:
            observed = ", ".join(
                f"{d.get('vendor','Unknown')} {d.get('product','')}".strip()
                for d in dets if isinstance(d, dict)
            )
        else:
            observed = "No external signals observed"

        likely_state = layer.get("likely_state")
        typical_risk = layer.get("typical_risk")

        out.append(f"## {idx}. {layer_name}")
        out.append(f"**Strategic importance:** {importance}")
        if rationale:
            out.append(f"*{rationale}*")
        out.append("")
        out.append(f"**Public visibility:** {visibility}")
        out.append(f"**Public signals observed:** {observed}")

        # When not visible, interpret rather than apologise
        if visibility != "Detected":
            if likely_state:
                out.append(f"**Likely internal state:** {likely_state}")
            if typical_risk:
                out.append(f"**Typical risk if unaddressed:** {typical_risk}")

        out.append("")
        out.append("**Next best step:**")
        out.append(_next_step_for_layer(layer_name))

        # NEW: vendor-neutral tool examples (only when gap/low visibility)
        tools_md = _render_tools_for_layer(layer_name, layer)
        if tools_md:
            out.append("")
            out.append(tools_md)

        out.append("")
        idx += 1

    return "\n".join(out).strip()


def _next_step_for_layer(layer_name: str) -> str:
    # Tight, MD-friendly next steps (vendor-neutral)
    name = (layer_name or "").lower()

    if "distribution" in name:
        return (
            "Confirm booking engine/CRS and channel manager, then validate two-way rate & inventory sync, "
            "parity controls, and automated restrictions (min stay/CTA/CTD) across key channels.\n\n"
            "**Decision to resolve:** Are distribution rules centrally governed or locally adjustable at property level?"
        )
    if "core" in name or "pms" in name or "rms" in name:
        return (
            "Confirm PMS + RMS (or manual process). Assess whether pricing decisions are automated, "
            "centrally governed, and consistently deployed across properties.\n\n"
            "**Decision to resolve:** Where does group control end and where does local pricing optimisation begin?"
        )
    if "guest" in name or "crm" in name:
        return (
            "Map guest data flows (web → booking → stay → post-stay). Identify the system of record for guest profiles "
            "and implement a single segmentation + consent model to power repeat/direct growth.\n\n"
            "**Decision to resolve:** Can the property activate campaigns locally, or is segmentation and execution centralised?"
        )
    if "commercial" in name or "attribution" in name or "tracking" in name:
        return (
            "Run an attribution audit (GTM/GA4 + booking funnel events + paid media pixels). Ensure booking conversion "
            "events, value capture, and channel grouping are consistent across properties.\n\n"
            "**Decision to resolve:** Can you reconcile marketing spend to bookings and revenue without debate?"
        )
    if "in-venue" in name or "experience" in name:
        return (
            "Identify the top 2–3 guest journey moments that drive satisfaction and spend (pre-arrival upsell, check-in, "
            "F&B ordering). Confirm integration points with PMS/POS.\n\n"
            "**Decision to resolve:** Which in-stay moments justify digital enablement without compromising brand experience?"
        )
    if "operations" in name:
        return (
            "Confirm housekeeping/maintenance/task tools and validate integration with PMS room status. Target the "
            "highest-friction workflows first (room turns, out-of-order, engineering response).\n\n"
            "**Decision to resolve:** Where are the biggest labour leaks caused by manual coordination?"
        )
    if "finance" in name or "reporting" in name:
        return (
            "Define 8–12 executive KPIs (RevPAR, GOPPAR, net ADR, direct share, CAC, repeat %, forecast accuracy). "
            "Build a single dashboard pulling from PMS/RMS/marketing sources with clear definitions.\n\n"
            "**Decision to resolve:** Do you have near-real-time, property-level performance visibility, or does reporting lag?"
        )
    return (
        "Confirm current tools and integration depth, then prioritise one high-leverage improvement for the next 30 days.\n\n"
        "**Decision to resolve:** What single change would unlock the most decision leverage in the next quarter?"
    )


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
    MD-grade report renderer (v2 + tool landscape).

    Supports:
    1) Full analysis dict from API
    2) Backwards-compatible minimal dict
    """
    payload = payload or {}

    scores = payload.get("scores", {}) or {}
    overall = scores.get("overall_score_0_to_100")

    url = payload.get("url")

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

    # Layers + roadmap (optional)
    layers = payload.get("layers", {}) or {}
    roadmap = payload.get("roadmap", {}) or {}

    score_lines = _score_composition_lines(scores)

    bench_line = ""
    if isinstance(typical_range, (list, tuple)) and len(typical_range) == 2:
        bic = f"{best_in_class}+" if best_in_class is not None else "—"
        bench_line = f"**Peer context:** Typical range **{typical_range[0]}–{typical_range[1]}** (best-in-class **{bic}**)"
    elif best_in_class is not None:
        bench_line = f"**Peer context:** Best-in-class **{best_in_class}+**"

    interp_line = f"**Interpretation:** {interpretation}" if interpretation else ""

    levers_md = "\n".join([f"- {x}" for x in levers]) if levers else ""
    scope_md = f"*{scope_note}*" if scope_note else ""

    # Opportunity confidence anchor (prevents range feeling arbitrary)
    opportunity_confidence = (
        "The **lower bound** reflects improvement from measurement, pricing hygiene, and reduced manual overhead. "
        "The **upper bound** assumes stronger integration between distribution, pricing, and guest data—"
        "without requiring wholesale system replacement."
    )

    # MD calibration paragraph
    md_calibration = (
        "### How to read this score\n"
        "Mid-range scores are common across both independent and group-affiliated hotels. "
        "This typically reflects core systems being in place, with the main constraint being **integration depth, "
        "property-level visibility, and measurement discipline**—not tool availability.\n"
    )

    # Render sections
    layers_md = _render_layers_md(layers) if layers else "Layer breakdown unavailable."
    roadmap_md = _render_roadmap_md(roadmap) if roadmap else ""
    tools_shortlist_md = _render_tools_shortlist_md(layers) if layers else ""

    return f"""
# Hotel Technology & Revenue Readiness Assessment — Executive Summary

{f"**Property:** {url}" if url else ""}

## Executive overview

**Technology Readiness Score:** {overall} / 100  
{bench_line}
{interp_line}

{md_calibration}

**Score composition:**
{chr(10).join(score_lines)}

**Estimated Annual Opportunity:** {_fmt_currency(low)} – {_fmt_currency(high)}  
{opportunity_confidence}
{scope_md}

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

## Technology stack assessment (by layer)

{layers_md}

---

{tools_shortlist_md if tools_shortlist_md else ""}

---

## Methodology & disclosures
- Public website and booking-journey signal analysis (where accessible)
- Confidence-scored detection and structured inference when signals are not visible
- No access to private systems, credentials, or guest data
- Vendor-neutral and free from referral or commission bias
""".strip()
