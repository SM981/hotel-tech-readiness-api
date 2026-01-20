"""
MD-grade report renderer for Hotel Technology & Revenue Readiness

Design principles:
- Unknown ≠ absence → always infer a likely internal state
- Every gap resolves into an executive decision
- Vendor-neutral, but concrete
- Financial impact only where defensible; otherwise frame as decision leverage
- C-suite readable from a single URL scan
"""

# ------------------------------------------------------------
# Opportunity model (REQUIRED – fixes Render import error)
# ------------------------------------------------------------

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

    # Conservative, first-order uplift only
    low = room_revenue * 0.013
    high = room_revenue * 0.05

    return {
        "assumptions": {
            "rooms": rooms,
            "occupancy": occupancy,
            "adr": adr,
        },
        "annual_opportunity_gbp_range": [
            round(low, 0),
            round(high, 0),
        ],
        "scope_note": (
            "Indicative first-order impact only. Excludes longer-term guest lifetime value, "
            "portfolio-level compounding, and brand effects."
        ),
    }


# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------

def _safe_list(x):
    return x if isinstance(x, list) else []


def _fmt_currency(value) -> str:
    try:
        return f"£{int(round(value)):,}"
    except Exception:
        return "£—"


def _fmt_pct(value) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except Exception:
        return "—%"


# ------------------------------------------------------------
# Hospitality tool landscape (illustrative, vendor-neutral)
# ------------------------------------------------------------

TOOL_LANDSCAPE = {
    "Distribution": {
        "Booking engine / CRS": [
            "Sabre SynXis", "SiteMinder", "D-EDGE", "TravelClick", "Avvio"
        ],
        "Channel management": [
            "SiteMinder", "DerbySoft", "RateGain", "STAAH"
        ],
        "Rate intelligence / parity": [
            "Lighthouse", "OTA Insight"
        ],
    },
    "Core Systems": {
        "Property Management System (PMS)": [
            "Oracle OPERA", "Guestline", "Mews", "protel", "Stayntouch"
        ],
        "Revenue Management System (RMS)": [
            "Duetto", "IDeaS", "Atomize", "Pace"
        ],
    },
    "Guest Data & CRM": {
        "CRM / guest profile": [
            "Revinate", "Cendyn", "Salesforce", "HubSpot"
        ],
        "Lifecycle & email automation": [
            "Revinate", "Cendyn", "Klaviyo"
        ],
        "Reputation & feedback": [
            "ReviewPro", "TrustYou", "Medallia"
        ],
    },
    "Commercial Execution": {
        "Analytics & attribution": [
            "GA4", "Looker Studio", "Adobe Analytics"
        ],
        "Tag governance": [
            "Google Tag Manager"
        ],
        "Metasearch": [
            "Google Hotel Ads", "Tripadvisor", "Trivago"
        ],
    },
    "In-Venue Experience": {
        "Guest messaging": [
            "HelloShift", "ALICE", "Akia"
        ],
        "Mobile check-in / keys": [
            "Duve", "AeroGuest", "Virdee", "SALTO"
        ],
        "Upsell & pre-arrival": [
            "Oaky", "Duve"
        ],
    },
    "Operations": {
        "Housekeeping & tasks": [
            "HotSOS", "Flexkeeping", "Optii", "ALICE"
        ],
        "Maintenance / engineering": [
            "HotSOS", "UpKeep"
        ],
    },
    "Finance & Reporting": {
        "Hotel BI & benchmarking": [
            "HotStats", "Lighthouse"
        ],
        "General BI": [
            "Power BI", "Looker Studio"
        ],
        "Accounting": [
            "Xero", "Sage"
        ],
    },
}

_TOOL_NOTE = (
    "*Examples reflect common patterns in comparable hotels. "
    "Actual selection depends on group governance, integration depth, budget, "
    "and operating model.*"
)


# ------------------------------------------------------------
# Layer rendering helpers
# ------------------------------------------------------------

def _decision_for_layer(name: str) -> str:
    n = name.lower()
    if "distribution" in n:
        return (
            "Are rates, availability and restrictions actively governed through systems, "
            "or managed reactively via OTAs and manual overrides?"
        )
    if "core" in n:
        return (
            "Is pricing driven by a documented revenue strategy supported by technology, "
            "or primarily by human judgement and historical patterns?"
        )
    if "guest" in n:
        return (
            "Do we have a single, usable guest profile across stays and spend, "
            "or fragmented data that limits repeat and personalisation?"
        )
    if "commercial" in n:
        return (
            "Can we reliably link marketing spend to bookings and revenue, "
            "or are optimisation decisions based on partial attribution?"
        )
    if "venue" in n:
        return (
            "Which in-stay moments are strategically important enough to digitise "
            "without compromising brand experience?"
        )
    if "operations" in n:
        return (
            "Where is manual coordination costing time, labour, or service consistency?"
        )
    if "finance" in n:
        return (
            "Is performance managed near-real-time, or retrospectively at month-end?"
        )
    return "What single change here would unlock the most decision leverage this quarter?"


def _good_state_for_layer(name: str) -> str:
    n = name.lower()
    if "distribution" in n:
        return (
            "- Automated two-way rate & inventory sync\n"
            "- Defined channel roles (direct vs OTA vs metasearch)\n"
            "- Active parity and restriction governance"
        )
    if "core" in n:
        return (
            "- PMS and RMS integrated\n"
            "- Pricing rules documented and governed\n"
            "- Forecasts actively used in decisions"
        )
    if "guest" in n:
        return (
            "- Single guest identity across systems\n"
            "- Consent-aware segmentation\n"
            "- Triggered lifecycle communications"
        )
    if "commercial" in n:
        return (
            "- GA4 capturing full booking funnel\n"
            "- Clean conversion signals into paid channels\n"
            "- Agreed attribution model"
        )
    if "venue" in n:
        return (
            "- Digital support at high-impact moments\n"
            "- PMS/POS-connected upsells\n"
            "- Measurable guest engagement"
        )
    if "operations" in n:
        return (
            "- Mobile task management\n"
            "- Live room status\n"
            "- Reduced handoffs and manual checks"
        )
    if "finance" in n:
        return (
            "- One executive dashboard\n"
            "- Agreed KPI definitions\n"
            "- Automated daily refresh from source systems"
        )
    return "- Clear ownership\n- Measurable outcomes\n- Reduced manual work"


def _render_layer_section(layer_name: str, layer: dict) -> str:
    dets = _safe_list(layer.get("detections"))
    importance = layer.get("strategic_importance", "Medium")
    rationale = layer.get("importance_rationale", "")

    observed = (
        ", ".join(
            f"{d.get('vendor','')} {d.get('product','')}".strip()
            for d in dets if isinstance(d, dict)
        )
        if dets else "No externally observable signals; system presence inferred from operating model."
    )

    likely_state = layer.get("likely_state") or (
        "Systems almost certainly exist internally but are abstracted behind group platforms "
        "or not directly connected to the public web layer."
    )

    typical_risk = layer.get("typical_risk") or (
        "Decision-making likely relies on delayed or manually consolidated data rather than live system signals."
    )

    tools = TOOL_LANDSCAPE.get(layer_name, {})

    out = []
    out.append(f"## {layer_name}")
    out.append(f"**Strategic importance:** {importance}")
    if rationale:
        out.append(f"*{rationale}*")
    out.append("")
    out.append(f"**Observed signals:** {observed}")
    out.append("")
    out.append(f"**Assumed internal state:** {likely_state}")
    out.append(f"**Risk if unaddressed:** {typical_risk}")
    out.append("")
    out.append("**Executive decision to resolve:**")
    out.append(_decision_for_layer(layer_name))
    out.append("")
    out.append("**What good looks like (≈90 days):**")
    out.append(_good_state_for_layer(layer_name))
    out.append("")

    if tools:
        out.append("**Common tools used in comparable hotels:**")
        for category, vendors in tools.items():
            out.append(f"- **{category}:** " + ", ".join(vendors[:4]))
        out.append("")
        out.append(_TOOL_NOTE)
        out.append("")

    return "\n".join(out).strip()


# ------------------------------------------------------------
# Main renderer
# ------------------------------------------------------------

def render_report_md(payload):
    """
    C-suite-ready report renderer.
    """
    payload = payload or {}

    url = payload.get("url", "")
    scores = payload.get("scores", {}) or {}
    layers = payload.get("layers", {}) or {}
    roadmap = payload.get("roadmap", {}) or {}
    benchmarks = payload.get("benchmarks", {}) or {}
    opportunity = payload.get("opportunity", {}) or {}

    overall = scores.get("overall_score_0_to_100")
    typical_range = benchmarks.get("typical_range")
    best_in_class = benchmarks.get("best_in_class")
    interpretation = benchmarks.get("interpretation")

    low, high = opportunity.get("annual_opportunity_gbp_range", [0, 0])
    assumptions = opportunity.get("assumptions", {}) or {}

    out = []

    out.append("# Hotel Technology & Revenue Readiness Assessment")
    if url:
        out.append(f"**Property reviewed:** {url}")
    out.append("")

    out.append("## Executive summary")
    out.append(f"**Technology Readiness Score:** {overall} / 100")
    if isinstance(typical_range, (list, tuple)):
        out.append(
            f"**Peer context:** Typical range {typical_range[0]}–{typical_range[1]} "
            f"(best-in-class {best_in_class}+)"
        )
    if interpretation:
        out.append(f"**Interpretation:** {interpretation}")
    out.append("")

    out.append(
        "This assessment focuses less on *whether systems exist* and more on "
        "*whether they are connected, visible, and decision-enabling at property level*."
    )
    out.append("")

    if low and high:
        out.append("**Indicative annual opportunity (conservative):** "
                   f"{_fmt_currency(low)} – {_fmt_currency(high)}")
        out.append(
            f"(Assumptions: {assumptions.get('rooms', 60)} rooms · "
            f"{_fmt_pct(assumptions.get('occupancy', 0.72))} occupancy · "
            f"£{assumptions.get('adr', 140)} ADR)"
        )
        out.append("")

    out.append("## Technology stack assessment (decision-led)")
    for layer_name in layers:
        out.append(_render_layer_section(layer_name, layers[layer_name]))
        out.append("")

    out.append("## 90-day MD agenda")
    for phase, obj in roadmap.items():
        out.append(f"### {phase}")
        if obj.get("outcome"):
            out.append(f"**Outcome:** {obj['outcome']}")
        if obj.get("exec_question"):
            out.append(f"**Executive question:** {obj['exec_question']}")
        out.append("")

    out.append("## Methodology & disclosures")
    out.append(
        "- Assessment based on publicly observable digital signals and sector benchmarks\n"
        "- No access to private systems, credentials, or guest data\n"
        "- Inferred states reflect common operating patterns in comparable hotels\n"
        "- Vendor-neutral and free from referral or commercial bias"
    )

    return "\n".join(out).strip()
