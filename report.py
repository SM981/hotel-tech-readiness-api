"""
MD-grade report renderer for Hotel Technology & Revenue Readiness.

Design principles:
- Unknown ≠ absence: never claim a system is missing unless proven; instead use Observed / Inferred / Unresolved.
- Every gap resolves into an executive decision and a proof path.
- Vendor-neutral, but concrete (illustrative tool landscape + integration-first language).
- Financial impact only where defensible; otherwise frame as decision leverage.
- C-suite readable from a single URL scan: include evidence register + booking-flow signals + competitor comparison when present.
- Fact-rooted: surface what we saw (domains, redirect destinations, tags, top signals).
"""

from typing import Any, Dict, List

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


def _truncate(s: str, n: int = 220) -> str:
    if not s:
        return ""
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _domain_from_url(u: str) -> str:
    try:
        from urllib.parse import urlparse
        return (urlparse(u).netloc or "").lower()
    except Exception:
        return ""


# ------------------------------------------------------------
# Tool landscape (hospitality-standard, vendor-neutral examples)
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
        "CRM / Guest profile": [
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
        "Tag & tracking governance": [
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
    "*Illustrative examples only. Selection depends on group governance, integration depth, budget, "
    "privacy/compliance constraints, and operating model.*"
)


# ------------------------------------------------------------
# Scoring render helpers (aligned to new scoring.py)
# ------------------------------------------------------------

def _score_composition_lines(scores: dict) -> list[str]:
    """
    Supports new scoring shape:
      layer_scores[*] = {layer, score, out_of, state, notes, signals}
    """
    layer_scores = _safe_list((scores or {}).get("layer_scores"))
    lines = []

    for item in layer_scores:
        if not isinstance(item, dict):
            continue

        name = item.get("layer", "Layer")
        score = item.get("score")
        out_of = item.get("out_of", 5)
        state = item.get("state")

        if score is not None:
            if state:
                lines.append(f"• {name}: {score} / {out_of} ({state})")
            else:
                lines.append(f"• {name}: {score} / {out_of}")

    return lines or ["• Score composition unavailable"]


def _render_top_signals(scores: dict) -> str:
    """
    Shows the strongest observed signals per layer (fact-rooted).
    """
    layer_scores = _safe_list((scores or {}).get("layer_scores"))
    out: List[str] = []

    out.append("## Evidence highlights (what we actually observed)")
    any_rows = False

    for ls in layer_scores:
        if not isinstance(ls, dict):
            continue

        layer = ls.get("layer", "Layer")
        signals = _safe_list(ls.get("signals"))

        # Only show when we have something concrete
        if not signals:
            continue

        any_rows = True
        out.append(f"### {layer}")

        for s in signals[:3]:
            if not isinstance(s, dict):
                continue
            vendor = s.get("vendor") or "Unknown"
            product = (s.get("product") or "").strip()
            src = (s.get("source") or "").strip()
            conf = s.get("confidence")
            conf_str = ""
            try:
                conf_str = f"{float(conf):.2f}"
            except Exception:
                conf_str = "—"

            label = f"{vendor} {product}".strip()
            if src:
                out.append(f"- {label} ({src}, confidence {conf_str})")
            else:
                out.append(f"- {label} (confidence {conf_str})")

        out.append("")

    if not any_rows:
        return (
            "## Evidence highlights (what we actually observed)\n"
            "No high-confidence vendor signals were surfaced in the public crawl. "
            "This is common for hotels where core systems are private or embedded behind the booking journey.\n"
        )

    return "\n".join(out).strip()


# ------------------------------------------------------------
# Evidence register (booking flow + domains + crawl notes)
# ------------------------------------------------------------

def _render_evidence_register(evidence: dict) -> str:
    e = evidence or {}
    booking = (e.get("booking_flow") or {})
    pages = _safe_list(e.get("pages_fetched"))
    domains = _safe_list(e.get("top_third_party_domains"))
    headers = e.get("headers_observed") or {}
    cookie_keys = _safe_list(e.get("cookie_keys_observed"))
    notes = _safe_list(e.get("crawl_notes"))
    errs = _safe_list(e.get("crawl_errors"))

    out: List[str] = []
    out.append("## Evidence register (public signals)")

    # Booking flow is often the most valuable “single URL” unlock
    out.append("### Booking journey signals")
    candidates = _safe_list(booking.get("candidates"))
    final_url = booking.get("final_url")
    final_domain = booking.get("final_domain")

    if candidates:
        out.append(f"- Booking CTA candidates (sample): {', '.join([_truncate(c, 90) for c in candidates[:3]])}")
    else:
        out.append("- Booking CTA candidates: none discovered in sampled pages")

    if final_url:
        out.append(f"- Booking journey final URL: {_truncate(final_url, 180)}")
    if final_domain:
        out.append(f"- Booking journey final domain: `{final_domain}`")
    else:
        out.append("- Booking journey final domain: not resolved (may be JS-driven, blocked, or embedded)")

    # Pages fetched
    if pages:
        out.append("\n### Pages fetched (sample)")
        for p in pages[:8]:
            if not isinstance(p, dict):
                continue
            u = p.get("url")
            st = p.get("status")
            ct = p.get("content_type")
            if u:
                out.append(f"- {u} (HTTP {st}, {ct})")

    # Domains observed
    if domains:
        out.append("\n### Third-party domains observed (top)")
        out.append("- " + ", ".join([f"`{d}`" for d in domains[:18] if isinstance(d, str)]))

    # Headers / cookie keys (very useful for infra/tooling hints)
    if headers:
        out.append("\n### Response headers (selected)")
        for k, v in list(headers.items())[:8]:
            out.append(f"- {k}: {v}")

    if cookie_keys:
        out.append("\n### Cookie keys observed (sample)")
        out.append("- " + ", ".join([f"`{c}`" for c in cookie_keys[:18] if isinstance(c, str)]))

    # Crawl notes/errors
    if notes:
        out.append("\n### Crawl notes")
        for n in notes[:6]:
            out.append(f"- {n}")

    if errs:
        out.append("\n### Crawl limitations (observed)")
        for er in errs[:4]:
            if isinstance(er, dict):
                out.append(f"- {er.get('type')}: {er.get('message')}")

    return "\n".join(out).strip()


# ------------------------------------------------------------
# Proof path + executive decision helpers
# ------------------------------------------------------------

def _proof_path(layer: dict) -> List[str]:
    pp = _safe_list((layer or {}).get("proof_path"))
    return [str(x) for x in pp if x]


def _decision_for_layer(name: str) -> str:
    n = (name or "").lower()
    if "distribution" in n:
        return (
            "Are distribution rules (rates, availability, restrictions) governed and automated end-to-end "
            "or managed reactively through OTAs and manual overrides?"
        )
    if "core" in n:
        return (
            "Is pricing and forecasting driven by a governed revenue system (with automation) "
            "or primarily by human judgement and historical patterns?"
        )
    if "guest" in n:
        return (
            "Do we have a single usable guest identity across stays/spend that can drive repeat/direct growth, "
            "or fragmented profiles that limit personalisation?"
        )
    if "commercial" in n:
        return (
            "Can we reliably link marketing spend to bookings/revenue, "
            "or are decisions being made on partial attribution?"
        )
    if "venue" in n:
        return (
            "Which in-stay moments are worth digitising (pre-arrival upsell, check-in, messaging) "
            "without compromising brand experience?"
        )
    if "operations" in n:
        return "Where is manual coordination costing time, labour, or service consistency most today?"
    if "finance" in n:
        return "Do we manage performance in near real time or retrospectively through month-end reporting?"
    return "What single change in this area would unlock the most decision leverage this quarter?"


def _good_state_for_layer(name: str) -> str:
    n = (name or "").lower()
    if "distribution" in n:
        return (
            "- Automated two-way rate and inventory sync\n"
            "- Clear channel roles (direct vs OTA vs metasearch)\n"
            "- Active parity and restriction governance"
        )
    if "core" in n:
        return (
            "- PMS and RMS integrated (or equivalent governed revenue controls)\n"
            "- Pricing rules documented with exceptions policy\n"
            "- Forecast cadence used in weekly trading decisions"
        )
    if "guest" in n:
        return (
            "- Single guest identity across booking → stay → post-stay\n"
            "- Consent-aware segmentation usable at property level\n"
            "- Triggered lifecycle communications (pre-arrival, post-stay, winback)"
        )
    if "commercial" in n:
        return (
            "- GA4 capturing full booking funnel (including booking engine)\n"
            "- Clean conversion signals into paid channels\n"
            "- Agreed attribution approach and governance"
        )
    if "venue" in n:
        return (
            "- Digital support at high-impact moments (pre-arrival, check-in, messaging)\n"
            "- PMS/POS-connected upsells where appropriate\n"
            "- Measurable adoption and guest satisfaction impact"
        )
    if "operations" in n:
        return (
            "- Mobile task management with accountability\n"
            "- Live room status and reduced handoffs\n"
            "- Engineering response times visible and managed"
        )
    if "finance" in n:
        return (
            "- One executive dashboard with 8–12 defined KPIs\n"
            "- Automated daily refresh from source systems\n"
            "- Reporting definitions owned and consistent"
        )
    return "- Clear ownership\n- Measurable outcomes\n- Reduced manual work"


# ------------------------------------------------------------
# Layer renderer (now aligned to Observed / Inferred / Unresolved + evidence)
# ------------------------------------------------------------

def _render_layer_section(layer_name: str, layer: dict) -> str:
    """
    Renders an MD-grade layer with:
    - Visibility state (Observed/Inferred/Unresolved)
    - Observed detections (incl. customer_confirmed)
    - Inferred state and risk framed as consequences
    - Proof path (how to make it knowable)
    - Executive decision + what good looks like
    - Tool landscape examples
    """
    layer = layer or {}

    visibility_state = layer.get("visibility_state") or layer.get("visibility") or "Inferred"
    importance = layer.get("strategic_importance", "Medium")
    rationale = layer.get("importance_rationale", "")

    dets = _safe_list(layer.get("detections"))
    observed_signals = (
        ", ".join(
            f"{d.get('vendor','Unknown')} {d.get('product','')}".strip()
            for d in dets if isinstance(d, dict)
        )
        if dets else "No high-confidence vendor signals surfaced"
    )

    likely_state = layer.get("likely_state") or (
        "This capability is common in comparable hotels, but is not directly observable from public signals."
    )
    typical_risk = layer.get("typical_risk") or (
        "If integration/visibility is weak, decision-making tends to rely on lagging or manually consolidated information."
    )

    tools = TOOL_LANDSCAPE.get(layer_name, {})
    proof = _proof_path(layer)

    out: List[str] = []
    out.append(f"## {layer_name}")
    out.append(f"**Strategic importance:** {importance}")
    if rationale:
        out.append(f"*{rationale}*")
    out.append("")
    out.append(f"**Visibility state:** {visibility_state}")
    out.append(f"**Observed signals:** {observed_signals}")
    out.append("")
    out.append(f"**Likely internal state (inference):** {likely_state}")
    out.append(f"**Risk if unaddressed:** {typical_risk}")
    out.append("")

    if proof:
        out.append("**How this becomes knowable (proof path):**")
        for p in proof[:3]:
            out.append(f"- {p}")
        out.append("")

    out.append("**Executive decision to resolve:**")
    out.append(_decision_for_layer(layer_name))
    out.append("")
    out.append("**What good looks like (90 days):**")
    out.append(_good_state_for_layer(layer_name))
    out.append("")

    if tools:
        out.append("**Common tools used in comparable hotels (illustrative):**")
        for category, vendors in tools.items():
            out.append(f"- **{category}:** " + ", ".join(vendors[:4]))
        out.append("")
        out.append(_TOOL_NOTE)
        out.append("")

    return "\n".join(out).strip()


# ------------------------------------------------------------
# Comparison renderer (optional, fact-rooted)
# ------------------------------------------------------------

def _render_comparison(payload: dict) -> str:
    comp = (payload or {}).get("comparison") or {}
    competitor = (payload or {}).get("competitor") or {}

    if not competitor:
        return ""

    out: List[str] = []
    out.append("## Competitor comparison (public-signal based)")

    a_url = payload.get("url") or ""
    b_url = competitor.get("url") or ""
    a_score = (payload.get("scores") or {}).get("overall_score_0_to_100")
    b_score = (competitor.get("scores") or {}).get("overall_score_0_to_100")

    out.append(f"- Primary: {a_url}")
    out.append(f"- Competitor: {b_url}")
    out.append("")

    if a_score is not None and b_score is not None:
        out.append(f"**Score comparison:** {a_score} vs {b_score}")
    if comp.get("score_delta") is not None:
        out.append(f"**Delta (primary - competitor):** {comp.get('score_delta')} points")
    out.append("")

    layer_deltas = _safe_list(comp.get("layer_deltas"))
    if layer_deltas:
        out.append("**Largest layer deltas (directional):**")
        # show top 4 by absolute delta
        try:
            layer_deltas = sorted(layer_deltas, key=lambda x: abs(float(x.get("delta", 0))), reverse=True)
        except Exception:
            pass
        for d in layer_deltas[:4]:
            if not isinstance(d, dict):
                continue
            out.append(f"- {d.get('layer')}: {d.get('delta')}")

    a_dom = comp.get("booking_engine_domain_a")
    b_dom = comp.get("booking_engine_domain_b")
    if a_dom or b_dom:
        out.append("")
        out.append("**Booking journey domains (often the strongest public hint):**")
        if a_dom:
            out.append(f"- Primary booking domain: `{a_dom}`")
        if b_dom:
            out.append(f"- Competitor booking domain: `{b_dom}`")

    notes = _safe_list(comp.get("notes"))
    if notes:
        out.append("")
        for n in notes[:3]:
            out.append(f"- {n}")

    return "\n".join(out).strip()


# ------------------------------------------------------------
# Main renderer
# ------------------------------------------------------------

def render_report_md(payload):
    """
    C-suite-ready report renderer (vNext).
    Designed to work with new app.py + scoring.py outputs:
      - visibility_state (Observed/Inferred/Unresolved)
      - evidence register (booking flow, domains, pages)
      - scoring signals per layer
      - optional competitor comparison
    """
    payload = payload or {}

    url = payload.get("url", "")
    scores = payload.get("scores", {}) or {}
    layers = payload.get("layers", {}) or {}
    roadmap = payload.get("roadmap", {}) or {}
    benchmarks = payload.get("benchmarks", {}) or {}
    segment_inf = payload.get("segment_inference", {}) or {}
    evidence = payload.get("evidence", {}) or {}
    confirmations = (payload.get("confirmations") or {}).get("provided") or {}

    overall = scores.get("overall_score_0_to_100")
    typical_range = benchmarks.get("typical_range")
    best_in_class = benchmarks.get("best_in_class")
    interpretation = benchmarks.get("interpretation")

    bench_line = ""
    if isinstance(typical_range, (list, tuple)) and len(typical_range) == 2:
        bench_line = f"Typical peer range: {typical_range[0]}–{typical_range[1]} (best-in-class {best_in_class}+)"
    elif best_in_class is not None:
        bench_line = f"Best-in-class benchmark: {best_in_class}+"

    # Opportunity (only show if present + numeric)
    opp = payload.get("opportunity", {}) or {}
    opp_rng = opp.get("annual_opportunity_gbp_range") or []
    show_financials = False
    low = high = None
    if isinstance(opp_rng, list) and len(opp_rng) == 2:
        try:
            low = float(opp_rng[0])
            high = float(opp_rng[1])
            if low >= 0 and high >= 0:
                show_financials = True
        except Exception:
            show_financials = False

    out: List[str] = []

    out.append("# Hotel Technology & Revenue Readiness Assessment")
    if url:
        out.append(f"**Property reviewed:** {url}")
    out.append("")

    # Segment inference (explicitly labelled)
    seg = segment_inf.get("segment")
    seg_conf = segment_inf.get("confidence")
    seg_ev = _safe_list(segment_inf.get("evidence"))
    if seg:
        out.append("## Context (public-signal inference)")
        out.append(f"**Likely segment:** {seg} ({seg_conf} confidence)")
        if seg_ev:
            out.append("**Evidence (sample):** " + "; ".join([_truncate(x, 140) for x in seg_ev[:2]]))
        out.append("")

    out.append("## Executive summary")
    out.append(f"**Technology Readiness Score:** {overall} / 100")
    if bench_line:
        out.append(f"**Peer context:** {bench_line}")
    if interpretation:
        out.append(f"**Interpretation:** {interpretation}")
    out.append("")

    if show_financials:
        out.append(f"**Indicative annual opportunity (modelled):** {_fmt_currency(low)} – {_fmt_currency(high)}")
        scope_note = opp.get("scope_note")
        if scope_note:
            out.append(f"*{scope_note}*")
    else:
        out.append(
            "**Commercial impact framing:** "
            "This report prioritises decision leverage (integration, measurement, automation). "
            "Where property inputs are not provided, financial impact should be treated as indicative rather than precise."
        )
    out.append("")

    # Confirmations (if any) so the report reads “complete” without overstating
    if confirmations:
        out.append("**Systems confirmed by the operator (not public signals):**")
        for k, v in confirmations.items():
            out.append(f"- {k.replace('_', ' ').title()}: {v}")
        out.append("")

    out.append(
        "This assessment focuses less on whether systems exist and more on whether they are "
        "**connected, measurable, and decision-enabling at property level**."
    )
    out.append("")

    out.append("## Score composition (by layer)")
    out.extend(_score_composition_lines(scores))
    out.append("")

    # Evidence highlights (per-layer signals from scoring.py)
    out.append(_render_top_signals(scores))
    out.append("")

    # Evidence register (crawl + booking journey)
    out.append(_render_evidence_register(evidence))
    out.append("")

    # Comparison (optional)
    comp_md = _render_comparison(payload)
    if comp_md:
        out.append(comp_md)
        out.append("")

    # Layer-by-layer (decision-led)
    out.append("## Technology stack assessment (decision-led)")
    # Preserve canonical ordering if possible
    ordered_layers = []
    for nm in TOOL_LANDSCAPE.keys():
        if nm in layers:
            ordered_layers.append(nm)
    # Include any extras
    for nm in layers.keys():
        if nm not in ordered_layers:
            ordered_layers.append(nm)

    for layer_name in ordered_layers:
        if layer_name not in layers:
            continue
        out.append(_render_layer_section(layer_name, layers[layer_name]))
        out.append("")

    # 90-day agenda
    out.append("## 90-day MD agenda")
    for phase, obj in (roadmap or {}).items():
        if not isinstance(obj, dict):
            continue
        out.append(f"### {phase}")
        if obj.get("outcome"):
            out.append(f"**Outcome:** {obj['outcome']}")
        if obj.get("exec_question"):
            out.append(f"**Executive question:** {obj['exec_question']}")
        out.append("")

    out.append("## Methodology & disclosures")
    out.append(
        "- Assessment based on bounded public-signal crawl (homepage + selected internal pages + booking CTA discovery where accessible)\n"
        "- No access to private systems, credentials, reservation emails, or guest data\n"
        "- Visibility is reported as Observed / Inferred / Unresolved (lack of observation does not imply absence)\n"
        "- Tool examples are illustrative and vendor-neutral; integration health and governance matter more than vendor choice\n"
        "- Competitor comparison (if included) uses identical public-signal methods for both sites"
    )

    return "\n".join(out).strip()
