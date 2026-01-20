"""
Executive-grade (V2) report renderer for Hotel Technology & Revenue Readiness.

Design principles:
- "Unknown" is not a report output state. Use: Observed / Inferred / Unresolved.
- Every inferred gap includes: consequence, proof path, executive decision, and 90-day definition of done.
- Vendor-neutral, evidence-led (public signals + booking journey plumbing).
- Financials are scenario modelling only: transparent assumptions + formula. If inputs missing, defaults are explicit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# ------------------------------------------------------------
# Commercial model (scenario only, transparent)
# ------------------------------------------------------------

def opportunity_model(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scenario-only commercial upside range.
    Uses conservative uplift band and explicit assumptions.

    Note: This is NOT a forecast. It is a sensitivity range based on room revenue only.
    """
    inputs = inputs or {}
    rooms = inputs.get("rooms")
    occupancy = inputs.get("occupancy")
    adr = inputs.get("adr")

    rooms = 60 if rooms is None else rooms
    occupancy = 0.72 if occupancy is None else occupancy
    adr = 140 if adr is None else adr

    try:
        room_revenue = float(rooms) * 365.0 * float(occupancy) * float(adr)
    except Exception:
        room_revenue = 0.0

    # Conservative uplift range (scenario band)
    low_pct = 0.013
    high_pct = 0.05

    low = room_revenue * low_pct
    high = room_revenue * high_pct

    return {
        "status": "scenario_only",
        "assumptions": {"rooms": rooms, "occupancy": occupancy, "adr": adr},
        "derived": {"room_revenue": round(room_revenue, 2)},
        "uplift_range": {
            "low_pct": low_pct,
            "high_pct": high_pct,
            "low_gbp": round(low, 0),
            "high_gbp": round(high, 0),
        },
        "primary_levers": [
            "Pricing accuracy and rate agility",
            "Direct mix and OTA cost control",
            "Repeat revenue via guest data automation",
            "Reduced manual reporting overhead",
        ],
        "disclosure": (
            "Scenario modelling only. Based on room revenue sensitivity to improved commercial execution. "
            "Excludes F&B/events/spa uplift, longer-term LTV compounding, and portfolio effects."
        ),
    }


# ------------------------------------------------------------
# Formatting helpers
# ------------------------------------------------------------

def _safe_list(x):
    return x if isinstance(x, list) else []


def _fmt_currency(value: Any) -> str:
    try:
        return f"£{int(round(float(value))):,}"
    except Exception:
        return "£—"


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except Exception:
        return "—%"


def _first_non_empty(*vals: Any) -> Optional[str]:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _layer_order() -> List[str]:
    return [
        "Distribution",
        "Core Systems",
        "Guest Data & CRM",
        "Commercial Execution",
        "In-Venue Experience",
        "Operations",
        "Finance & Reporting",
    ]


def _status_badge(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "observed":
        return "Observed"
    if s == "inferred":
        return "Inferred"
    if s == "unresolved":
        return "Unresolved"
    return "Inferred"


def _evidence_strength(detections: List[Dict[str, Any]], status: str) -> str:
    """
    Evidence strength is an explanatory label, not a claim of internal usage.
    """
    st = (status or "").lower()
    if st == "observed":
        # strongest confidence among detections
        best = 0.0
        for d in detections or []:
            try:
                best = max(best, float(d.get("confidence", 0) or 0))
            except Exception:
                continue
        if best >= 0.85:
            return "High"
        if best >= 0.55:
            return "Medium"
        return "Low"
    if st == "inferred":
        return "Low"
    return "Low"


# ------------------------------------------------------------
# Tool landscape (illustrative, vendor-neutral examples)
# ------------------------------------------------------------

TOOL_LANDSCAPE: Dict[str, Dict[str, List[str]]] = {
    "Distribution": {
        "Booking engine / CRS": ["Sabre SynXis", "SiteMinder", "D-EDGE", "TravelClick", "Avvio"],
        "Channel management": ["SiteMinder", "DerbySoft", "RateGain", "STAAH"],
        "Rate intelligence / parity": ["Lighthouse", "OTA Insight"],
        "Metasearch": ["Google Hotel Ads", "Tripadvisor", "Trivago"],
    },
    "Core Systems": {
        "PMS": ["Oracle OPERA", "Guestline", "Mews", "protel", "Stayntouch"],
        "RMS": ["Duetto", "IDeaS", "Atomize", "Pace"],
    },
    "Guest Data & CRM": {
        "CRM / Guest profile": ["Revinate", "Cendyn", "Salesforce", "HubSpot"],
        "Lifecycle & email automation": ["Revinate", "Cendyn", "Klaviyo"],
        "Reputation & feedback": ["ReviewPro", "TrustYou", "Medallia"],
    },
    "Commercial Execution": {
        "Analytics & BI": ["GA4", "Looker Studio", "Power BI"],
        "Tag management": ["Google Tag Manager"],
        "Paid media measurement": ["Google Ads", "Meta Pixel", "Floodlight (CM360)"],
    },
    "In-Venue Experience": {
        "Guest messaging": ["HelloShift", "ALICE", "Akia"],
        "Mobile check-in / keys": ["Duve", "AeroGuest", "Virdee", "SALTO"],
        "Upsell & pre-arrival": ["Oaky", "Duve"],
    },
    "Operations": {
        "Housekeeping & tasks": ["HotSOS", "Flexkeeping", "Optii", "ALICE"],
        "Maintenance / engineering": ["HotSOS", "UpKeep"],
    },
    "Finance & Reporting": {
        "Hotel BI & benchmarking": ["HotStats", "Lighthouse"],
        "General BI": ["Power BI", "Looker Studio"],
        "Accounting": ["Xero", "Sage"],
    },
}

_TOOL_NOTE = (
    "*Illustrative examples only. Selection depends on group governance, integration depth, budget, "
    "and operating model. This report does not recommend vendors.*"
)


# ------------------------------------------------------------
# Stack shaping helpers (ensure "full tech stack" output)
# ------------------------------------------------------------

def _build_full_stack_list(stack_by_layer: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Create a flattened "full stack" view suitable for exec reading.
    Uses observed detections where present, otherwise inferred/unresolved.
    """
    out: List[Dict[str, Any]] = []

    for layer in _layer_order():
        layer_obj = (stack_by_layer or {}).get(layer, {}) or {}
        status = _status_badge(layer_obj.get("visibility_state") or layer_obj.get("visibility") or "Inferred")
        dets = _safe_list(layer_obj.get("detections"))
        proof = _safe_list(layer_obj.get("proof_path"))

        primary = None
        evidence_strength = _evidence_strength(dets, status)

        if dets:
            # pick the highest confidence item
            best = None
            best_c = -1.0
            for d in dets:
                if not isinstance(d, dict):
                    continue
                try:
                    c = float(d.get("confidence", 0) or 0)
                except Exception:
                    c = 0.0
                if c > best_c:
                    best_c = c
                    best = d
            if best:
                v = (best.get("vendor") or "").strip()
                p = (best.get("product") or "").strip()
                primary = (v + " " + p).strip() or None

        out.append({
            "layer": layer,
            "status": status,
            "primary_candidate": primary,
            "evidence_strength": evidence_strength,
            "proof_path": (proof[0] if proof else "Follow booking journey redirects and inspect scripts/cookies for vendor signals."),
        })

    return out


# ------------------------------------------------------------
# Section renderers
# ------------------------------------------------------------

def _render_exec_summary(payload: Dict[str, Any]) -> str:
    meta = payload.get("meta", {}) or {}
    url = meta.get("url") or payload.get("url") or ""
    prop_name = meta.get("property_name") or ""

    scores = payload.get("scores", {}) or payload.get("scores", {}) or {}
    overall = (scores or {}).get("overall_score_0_to_100")

    peer = (scores or {}).get("peer_context") or payload.get("benchmarks") or {}
    interpretation = peer.get("interpretation")
    typical_range = peer.get("typical_range")
    best_in_class = peer.get("best_in_class")

    # Commercial model
    cm = payload.get("commercial_model") or payload.get("opportunity") or {}
    upl = cm.get("uplift_range") or {}
    low_gbp = upl.get("low_gbp")
    high_gbp = upl.get("high_gbp")

    bench_line = ""
    if isinstance(typical_range, (list, tuple)) and len(typical_range) == 2:
        bench_line = f"Peer context: typical {typical_range[0]}–{typical_range[1]} (best-in-class {best_in_class}+)"
    elif best_in_class is not None:
        bench_line = f"Peer context: best-in-class {best_in_class}+"

    lines: List[str] = []
    lines.append("# Hotel Technology & Revenue Readiness Assessment (V2)")
    if prop_name:
        lines.append(f"**Property:** {prop_name}")
    if url:
        lines.append(f"**Website scanned:** {url}")
    lines.append("")

    lines.append("## Executive summary")
    lines.append(f"**Technology Readiness Score:** {overall} / 100")
    if bench_line:
        lines.append(f"**{bench_line}**")
    if interpretation:
        lines.append(f"**Interpretation:** {interpretation}")
    lines.append("")

    # Scenario-only opportunity line (never presented as certainty)
    if isinstance(low_gbp, (int, float)) and isinstance(high_gbp, (int, float)) and high_gbp > 0:
        lines.append(f"**Commercial upside (scenario range):** {_fmt_currency(low_gbp)} – {_fmt_currency(high_gbp)}")
        disclosure = cm.get("disclosure")
        if disclosure:
            lines.append(f"*{disclosure}*")
    else:
        lines.append("**Commercial upside:** Not quantified in this run (scenario model unavailable).")
    lines.append("")

    lines.append(
        "This report is evidence-led from a bounded public crawl (including booking journey plumbing where discoverable). "
        "Capabilities are labelled **Observed / Inferred / Unresolved**—lack of public visibility is not treated as absence."
    )

    return "\n".join(lines).strip()


def _render_evidence(payload: Dict[str, Any]) -> str:
    ev = payload.get("evidence", {}) or {}
    crawl = ev.get("crawl", {}) or ev
    booking = ev.get("booking_flow", {}) or {}

    pages = _safe_list(crawl.get("pages_fetched"))
    domains = _safe_list(crawl.get("top_third_party_domains"))
    cookie_keys = _safe_list(crawl.get("cookie_keys_observed"))

    final_domain = booking.get("final_domain")
    redirect_chain = _safe_list(booking.get("redirect_chain"))
    booking_cookies = _safe_list(booking.get("cookie_keys"))

    out: List[str] = []
    out.append("## Evidence register (public signals)")
    if final_domain:
        out.append(f"- **Booking journey final domain:** `{final_domain}`")
    if redirect_chain:
        out.append(f"- **Booking redirect chain (sample):** " + " → ".join([f"`{x}`" for x in redirect_chain[:4]]) + (" …" if len(redirect_chain) > 4 else ""))
    if booking_cookies:
        out.append(f"- **Booking cookie keys (sample):** " + ", ".join([f"`{x}`" for x in booking_cookies[:10]]) + (" …" if len(booking_cookies) > 10 else ""))

    if domains:
        out.append(f"- **Third-party domains observed (sample):** " + ", ".join([f"`{d}`" for d in domains[:12]]) + (" …" if len(domains) > 12 else ""))

    if cookie_keys and not booking_cookies:
        out.append(f"- **Site cookie keys observed (sample):** " + ", ".join([f"`{k}`" for k in cookie_keys[:12]]) + (" …" if len(cookie_keys) > 12 else ""))

    if pages:
        out.append(f"- **Pages fetched:** {len(pages)} (bounded crawl)")
    errs = _safe_list(crawl.get("crawl_errors"))
    if errs:
        out.append(f"- **Crawl errors:** {len(errs)} (non-fatal)")
    out.append("")
    return "\n".join(out).strip()


def _render_stack_table(full_stack_list: List[Dict[str, Any]]) -> str:
    out: List[str] = []
    out.append("## Tech stack view (capability coverage)")
    out.append("| Layer | Status | Primary observed candidate | Evidence strength | Proof path |")
    out.append("|---|---|---|---|---|")
    for row in full_stack_list:
        out.append(
            f"| {row.get('layer','')} | {row.get('status','')} | {row.get('primary_candidate') or '—'} | "
            f"{row.get('evidence_strength','Low')} | {row.get('proof_path','')} |"
        )
    out.append("")
    return "\n".join(out).strip()


def _render_layer(layer_name: str, layer_obj: Dict[str, Any]) -> str:
    status = _status_badge(layer_obj.get("visibility_state") or layer_obj.get("visibility") or "Inferred")
    importance = layer_obj.get("strategic_importance", "Medium")
    rationale = layer_obj.get("importance_rationale") or ""
    dets = _safe_list(layer_obj.get("detections"))

    likely_state = layer_obj.get("likely_state") or ""
    typical_risk = layer_obj.get("typical_risk") or ""
    proof = _safe_list(layer_obj.get("proof_path"))
    decision = layer_obj.get("exec_decision") or ""
    good = _safe_list(layer_obj.get("what_good_looks_like_90d"))

    # Observed signals summary
    observed_lines: List[str] = []
    if dets:
        # show up to 4 signals
        for d in dets[:4]:
            if not isinstance(d, dict):
                continue
            v = (d.get("vendor") or "").strip()
            p = (d.get("product") or "").strip()
            lab = (d.get("label") or "").strip()
            src = (d.get("source") or "").strip()
            conf = d.get("confidence", "")
            evidence = _safe_list(d.get("evidence"))
            ev_snip = f" — {evidence[0]}" if evidence else ""
            observed_lines.append(f"- **{(v + ' ' + p).strip()}** ({lab}, {conf}, {src}){ev_snip}")
    else:
        observed_lines.append("- No vendor/product signals were directly observable from the public crawl for this layer.")

    # Tool options (illustrative)
    tools = layer_obj.get("tool_options") or TOOL_LANDSCAPE.get(layer_name) or {}

    out: List[str] = []
    out.append(f"### {layer_name}")
    out.append(f"**Status:** {status}  |  **Strategic importance:** {importance}")
    if rationale:
        out.append(f"*{rationale}*")
    out.append("")
    out.append("**Observed signals:**")
    out.extend(observed_lines)
    out.append("")

    if status != "Observed":
        if likely_state:
            out.append(f"**Inferred internal state:** {likely_state}")
        if typical_risk:
            out.append(f"**Consequence if left unresolved:** {typical_risk}")
        if proof:
            out.append("**Fastest proof path (public / single-URL adjacent):**")
            out.extend([f"- {x}" for x in proof[:4]])
        out.append("")

    if decision:
        out.append("**Executive decision this gap resolves into:**")
        out.append(f"- {decision}")
        out.append("")

    if good:
        out.append("**What good looks like in 90 days:**")
        out.extend([f"- {x}" for x in good[:6]])
        out.append("")

    if tools:
        out.append("**Common tool options in comparable hotels (illustrative):**")
        for cap, vendors in tools.items():
            if isinstance(vendors, list) and vendors:
                out.append(f"- **{cap}:** " + ", ".join(vendors[:4]))
        out.append(_TOOL_NOTE)

    return "\n".join(out).strip()


def _render_comparison(payload: Dict[str, Any]) -> str:
    comp = payload.get("comparison") or {}
    competitor = payload.get("competitor") or {}

    if not comp:
        return ""

    out: List[str] = []
    out.append("## Competitor comparison (public-signal)")
    delta = comp.get("score_delta")
    if delta is not None:
        out.append(f"**Score delta (property - competitor):** {delta:+.1f} points")
    a_dom = comp.get("booking_engine_domain_a")
    b_dom = comp.get("booking_engine_domain_b")
    if a_dom or b_dom:
        out.append(f"- Booking domain (property): `{a_dom or '—'}`")
        out.append(f"- Booking domain (competitor): `{b_dom or '—'}`")

    layer_deltas = _safe_list(comp.get("layer_deltas"))
    if layer_deltas:
        out.append("")
        out.append("| Layer | Delta |")
        out.append("|---|---:|")
        for ld in layer_deltas:
            if isinstance(ld, dict) and ld.get("layer") is not None and ld.get("delta") is not None:
                out.append(f"| {ld['layer']} | {ld['delta']:+.1f} |")

    notes = _safe_list(comp.get("notes"))
    if notes:
        out.append("")
        out.extend([f"- {n}" for n in notes[:4]])

    # Light competitor pointer
    c_url = competitor.get("url")
    if c_url:
        out.append("")
        out.append(f"*Competitor scanned:* {c_url}")

    out.append("")
    return "\n".join(out).strip()


def _render_methodology(payload: Dict[str, Any]) -> str:
    cm = payload.get("commercial_model") or payload.get("opportunity") or {}
    disclosure = cm.get("disclosure") or "Scenario modelling is clearly labelled; no internal data is accessed."

    out: List[str] = []
    out.append("## Methodology & disclosures")
    out.append("- Bounded public crawl (homepage + selected internal links + booking CTA discovery where available).")
    out.append("- Signals derived from: script tags, iframes, form actions, redirect domains, cookie keys, and third-party domains.")
    out.append("- No authentication, no form submission, no privileged access, no guest data.")
    out.append(f"- Financials: {disclosure}")
    out.append("- Vendor-neutral; tool examples are illustrative only and not recommendations.")
    return "\n".join(out).strip()


# ------------------------------------------------------------
# Main renderer (V2)
# ------------------------------------------------------------

def render_report_md(payload: Dict[str, Any]) -> str:
    """
    Executive-grade markdown report.
    Accepts your analysis dict. Tolerates partial inputs.

    Expected keys (best effort):
    - meta/url
    - scores / benchmarks
    - stack.by_layer or layers
    - evidence
    - commercial_model/opportunity
    - comparison (optional)
    """
    payload = payload or {}

    # Normalize inputs from older versions
    meta = payload.get("meta") or {}
    if not meta.get("url") and payload.get("url"):
        meta["url"] = payload.get("url")
    payload["meta"] = meta

    # Normalize stack container
    stack = payload.get("stack") or {}
    stack_by_layer = (stack.get("by_layer") or payload.get("layers") or {})
    stack["by_layer"] = stack_by_layer
    payload["stack"] = stack

    # Ensure a full stack list exists
    full_stack_list = stack.get("full_stack_list")
    if not isinstance(full_stack_list, list) or not full_stack_list:
        full_stack_list = _build_full_stack_list(stack_by_layer)
        stack["full_stack_list"] = full_stack_list

    # Ensure a commercial model exists if opportunity exists
    if not payload.get("commercial_model") and payload.get("opportunity"):
        payload["commercial_model"] = payload.get("opportunity")

    sections: List[str] = []
    sections.append(_render_exec_summary(payload))
    sections.append("")
    sections.append(_render_evidence(payload))
    sections.append("")
    sections.append(_render_stack_table(full_stack_list))
    sections.append("")

    sections.append("## Layer-by-layer assessment (decision-led)")
    for layer_name in _layer_order():
        layer_obj = (stack_by_layer or {}).get(layer_name, {}) or {}
        sections.append(_render_layer(layer_name, layer_obj))
        sections.append("")

    comp_md = _render_comparison(payload)
    if comp_md:
        sections.append(comp_md)

    sections.append(_render_methodology(payload))

    return "\n".join([s for s in sections if isinstance(s, str) and s.strip()]).strip()
