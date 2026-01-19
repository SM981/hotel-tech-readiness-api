def render_report_md(payload):
    """
    MD-grade report renderer (v2).

    Supports two inputs:
    1) Full analysis dict from API:
       payload = {
         "url":..., "scores":..., "benchmarks":..., "layers":..., "roadmap":...,
         "opportunity":..., "segment_inference":..., "gaps":..., "exec_priorities_top3":...,
         "confirmations":...
       }

    2) Backwards-compatible minimal dict:
       payload = {"scores":..., "opportunity":...}
    """
    payload = payload or {}

    # -------------------------
    # Core fields
    # -------------------------
    scores = payload.get("scores", {}) or {}
    overall = scores.get("overall_score_0_to_100")

    url = payload.get("url")

    # Benchmarks (optional)
    benchmarks = payload.get("benchmarks", {}) or {}
    typical_range = benchmarks.get("typical_range")
    best_in_class = benchmarks.get("best_in_class")
    interpretation = benchmarks.get("interpretation")

    # Segment inference (optional, narrative upgrade)
    segment_inf = payload.get("segment_inference", {}) or {}
    inferred_segment = segment_inf.get("segment")
    inferred_conf = segment_inf.get("confidence")
    inferred_evidence = _safe_list(segment_inf.get("evidence"))
    inferred_implications = _safe_list(segment_inf.get("implications"))

    # Gaps + Exec priorities (optional)
    gaps = payload.get("gaps", {}) or {}
    gap_summary = _safe_list(gaps.get("gap_summary"))
    exec_priorities = _safe_list(payload.get("exec_priorities_top3"))

    # Confirmations (optional)
    confirmations = payload.get("confirmations", {}) or {}
    provided = confirmations.get("provided", {}) if isinstance(confirmations.get("provided", {}), dict) else {}
    confirmations_list = [f"- **{k.replace('_', ' ').title()}**: {v}" for k, v in provided.items() if v]

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
    layers = payload.get("layers", {}) or {}
    roadmap = payload.get("roadmap", {}) or {}

    # Score composition
    score_lines = _score_composition_lines(scores)

    # Peer context line
    bench_line = ""
    if isinstance(typical_range, (list, tuple)) and len(typical_range) == 2:
        bic = f"{best_in_class}+" if best_in_class is not None else "—"
        bench_line = f"**Peer context:** Typical range **{typical_range[0]}–{typical_range[1]}** (best-in-class **{bic}**)"
    elif best_in_class is not None:
        bench_line = f"**Peer context:** Best-in-class **{best_in_class}+**"

    interp_line = f"**Interpretation:** {interpretation}" if interpretation else ""

    # Build levers text
    levers_md = "\n".join([f"- {x}" for x in levers]) if levers else ""

    # Opportunity confidence anchor
    opportunity_confidence = (
        "The **lower bound** reflects improvement from measurement and pricing hygiene. "
        "The **upper bound** assumes stronger integration between distribution, pricing, and guest data—"
        "without requiring wholesale system replacement."
    )

    scope_md = f"*{scope_note}*" if scope_note else ""

    # Render layers + roadmap using existing helpers
    layers_md = _render_layers_md(layers) if layers else ""
    roadmap_md = _render_roadmap_md(roadmap) if roadmap else ""

    # -------------------------
    # MD calibration paragraph
    # -------------------------
    md_calibration = ""
    if isinstance(typical_range, (list, tuple)) and len(typical_range) == 2 and overall is not None:
        md_calibration = (
            "### How to read this score\n"
            "For many independent and group-affiliated hotels, scores in the **mid-range** are common. "
            "This usually reflects core systems being in place, with the main constraint being **integration depth, "
            "property-level visibility, and measurement discipline**—not tool availability.\n"
        )
    else:
        md_calibration = (
            "### How to read this assessment\n"
            "Where systems are not publicly visible, the aim is to surface **integration risk and decision leverage**, "
            "not to imply absence of core tools.\n"
        )

    # -------------------------
    # What’s probably true (segment inference)
    # -------------------------
    probably_true_md = ""
    if inferred_segment:
        evidence_md = "\n".join([f"- {e}" for e in inferred_evidence]) if inferred_evidence else ""
        implications_md = "\n".join([f"- {i}" for i in inferred_implications]) if inferred_implications else ""
        probably_true_md = (
            "### What is probably true (based on public signals)\n"
            f"- **Likely segment:** {inferred_segment} (confidence: {inferred_conf or 'Low'})\n"
            + (evidence_md and f"- **Evidence:**\n{evidence_md}\n" or "")
            + (implications_md and f"- **Implications for tech strategy:**\n{implications_md}\n" or "")
        )

    # -------------------------
    # Exec priorities (Top 3)
    # -------------------------
    exec_priorities_md = ""
    if exec_priorities:
        lines = ["## Top 3 executive priorities (next 90 days)"]
        for i, p in enumerate(exec_priorities[:3], start=1):
            if not isinstance(p, dict):
                continue
            title = p.get("title", f"Priority {i}")
            why_now = p.get("why_now")
            wgl = _safe_list(p.get("what_good_looks_like"))
            qs = _safe_list(p.get("exec_questions"))

            lines.append(f"### {i}. {title}")
            if why_now:
                lines.append(f"**Why now:** {why_now}")
            if wgl:
                lines.append("**What good looks like:**")
                lines.extend([f"- {x}" for x in wgl])
            if qs:
                lines.append("**Executive questions to resolve:**")
                lines.extend([f"- {x}" for x in qs])
            lines.append("")
        exec_priorities_md = "\n".join(lines).strip()

    # -------------------------
    # Confirmations (trust-first)
    # -------------------------
    confirmations_md = ""
    if confirmations_list:
        confirmations_md = (
            "## Confirmed systems provided\n"
            "The following items were provided by the hotel/team and treated as **confirmed** (source: customer-confirmed):\n"
            + "\n".join(confirmations_list)
            + "\n"
        )

    # -------------------------
    # Precision ask (low-friction)
    # -------------------------
    precision_ask = (
        "## What would materially improve precision\n"
        "Confirming **one** of the following would sharpen the readiness score and prioritisation materially:\n"
        "- PMS vendor **or**\n"
        "- Booking engine / CRS (and whether distribution & pricing are centrally governed vs locally optimised)\n"
    )

    # -------------------------
    # Methodology (tight + executive-safe)
    # -------------------------
    methodology = (
        "## Methodology & disclosures\n"
        "- Based on publicly observable website signals and accessible booking-journey signals (where available)\n"
        "- Confidence-scored detection and structured inference when systems are not externally visible\n"
        "- No access to private systems, credentials, or guest data\n"
        "- Vendor-neutral and free from referral or commission bias\n"
    )

    # -------------------------
    # Build final report
    # -------------------------
    title_line = "# Hotel Technology & Revenue Readiness Assessment — Executive Summary"
    property_line = f"**Property:** {url}" if url else ""

    primary_levers_fallback = "- Pricing and channel optimisation\n- Direct mix and margin control\n- Guest data automation\n- Reduced manual reporting overhead"

    return f"""
{title_line}

{property_line}

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
{levers_md if levers_md else primary_levers_fallback}

---

{probably_true_md if probably_true_md else ""}

---

{exec_priorities_md if exec_priorities_md else ""}

---

{roadmap_md if roadmap_md else ""}

---

{confirmations_md if confirmations_md else ""}

---

## Technology stack assessment (by layer)

{layers_md if layers_md else "Layer breakdown unavailable."}

---

{precision_ask}

---

{methodology}
""".strip()
