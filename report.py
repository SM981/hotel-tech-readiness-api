from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Tuple


FORBIDDEN_WORDS = {"likely", "inferred", "probably", "typical", "peer range", "best-in-class", "benchmark"}
JARGON = {"CRS", "RMS", "CDP", "API", "ETL", "attribution", "middleware", "webhook", "schema"}


def _today_iso() -> str:
    return date.today().isoformat()


def build_stack_register_rows(intake: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Converts intake stack into report stack_register rows.
    Guarantees all 10 categories appear (schema already enforces presence).
    """
    rows: List[Dict[str, Any]] = []

    def _emit(category: str, entry: Dict[str, Any]) -> None:
        rows.append(
            {
                "category": category,
                "vendor": entry.get("vendor", ""),
                "ownership": entry.get("ownership", "unknown"),
                "evidence_level": entry.get("evidence_level", "not_provided"),
                "notes": (entry.get("evidence_notes") or "").strip(),
            }
        )

    for cat in intake["stack"].keys():
        block = intake["stack"][cat]
        if isinstance(block, dict) and "systems" in block:
            for sys in block["systems"]:
                _emit(cat, sys)
        else:
            _emit(cat, block)

    # Some categories allow multi systems; output schema expects minItems 10 overall,
    # but duplicates are allowed for multi categories.
    return rows


def build_integration_map_rows(intake: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """
    Builds the canonical integration map. Status is never guessed:
    - If hotel provided explicit integrations_claimed we still treat link as Unknown unless they assert Active/Not active.
    This function produces 'unknown_not_confirmed' by default and returns a list of targeted unknowns to ask about.
    """
    entity = intake["entity"]
    # Canonical flows
    flows = [
        ("booking_engine", "pms", "reservations"),
        ("channel_manager_crs", "pms", "rates/availability"),
        ("rms", "pms", "pricing/forecast inputs & outputs"),
        ("pms", "crm_guest_db", "guest profiles/stay history"),
        ("crm_guest_db", "email_lifecycle", "segments/triggers"),
        ("pms", "finance_accounting", "posting"),
        ("pms", "reporting_bi", "KPIs/reporting"),
    ]

    def label(cat: str) -> str:
        names = {
            "pms": "PMS",
            "booking_engine": "Booking engine",
            "channel_manager_crs": "Channel manager / CRS",
            "rms": "RMS",
            "crm_guest_db": "CRM / guest database",
            "email_lifecycle": "Email / lifecycle marketing",
            "finance_accounting": "Finance / accounting",
            "reporting_bi": "Reporting / BI",
        }
        return names.get(cat, cat)

    rows: List[Dict[str, Any]] = []
    unknowns: List[Dict[str, str]] = []

    # Default all links to Unknown unless we add an explicit mechanism later for user to confirm.
    for f, t, data in flows:
        rows.append(
            {
                "from": f,
                "to": t,
                "data": data,
                "status": "unknown_not_confirmed",
                "confirmed_by": "Not confirmed",
                "symptom_if_broken": "Manual work or reporting gaps.",
            }
        )
        unknowns.append({"from_label": label(f), "to_label": label(t), "data": data})

    return rows, unknowns


def build_executive_summary(
    payload: Dict[str, Any],
    stack_rows: List[Dict[str, Any]],
    integration_rows: List[Dict[str, Any]],
    gaps: List[Dict[str, Any]],
    next_steps: Dict[str, Any],
    missing_categories: List[str],
    integration_unknowns: List[Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "report_date": _today_iso(),
        "confirmed_facts": [
            f"Tech stack register captured for {payload['entity']['name']} (scope: {payload['entity']['scope']})."
        ],
        "missing_items": missing_categories,
        "blocked_decisions": [g.get("decision_impaired") for g in gaps[:3] if g.get("decision_impaired")],
        "top_actions_0_30": [a["action"] for a in next_steps.get("days_0_30", [])[:5]],
        "integration_unknowns": integration_unknowns,
        "hotel_provided_evidence": [],  # populate if you ingest file references later
        "public_market_signals": [],    # populate if you ingest sources later
    }


def run_qa_gates(report_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns pass/fail and details.
    This is the enforcement layer. If this fails, the API must not publish a final report.
    """
    failures: List[Dict[str, str]] = []

    # QA-0: forbidden vocabulary
    as_text = str(report_json).lower()
    for w in FORBIDDEN_WORDS:
        if w in as_text:
            failures.append({"gate": "QA-0", "message": f"Forbidden word present: '{w}'"})

    # QA-1: mandatory categories exist
    required_cats = {
        "pms",
        "booking_engine",
        "channel_manager_crs",
        "rms",
        "crm_guest_db",
        "email_lifecycle",
        "in_stay_tools",
        "housekeeping_maintenance",
        "finance_accounting",
        "reporting_bi",
    }
    present_cats = {r["category"] for r in report_json.get("stack_register", []) if "category" in r}
    missing = sorted(list(required_cats - present_cats))
    if missing:
        failures.append({"gate": "QA-1", "message": f"Missing stack categories in stack_register: {missing}"})

    # QA-2: evidence level required
    for r in report_json.get("stack_register", []):
        if not r.get("evidence_level"):
            failures.append({"gate": "QA-2", "message": "Stack row missing evidence_level."})
            break

    # QA-3: integration map coverage
    if len(report_json.get("integration_map", [])) < 7:
        failures.append({"gate": "QA-3", "message": "Integration map does not include all canonical flows."})
    else:
        for row in report_json["integration_map"]:
            if row.get("status") not in {"active_confirmed", "not_active_confirmed", "unknown_not_confirmed"}:
                failures.append({"gate": "QA-3", "message": "Integration row has invalid or missing status."})
                break

    # QA-4: gaps must be CEO-valid
    for g in report_json.get("gaps", []):
        required = [
            "gap_name",
            "missing_or_broken_fact",
            "operational_symptom",
            "decision_impaired",
            "risk_if_unchanged",
            "owner_function",
            "close_gap_action",
        ]
        if any(not g.get(k) for k in required):
            failures.append({"gate": "QA-4", "message": f"Gap missing required CEO fields: {g.get('gap_name','(unnamed)')}"})
            break

    # QA-5: no fabricated ROI (basic numeric check in report text)
    # This is a lightweight guard: if currency signs appear in commercial_impact while quantified is false, fail.
    ci = report_json.get("commercial_impact", {})
    if not ci.get("quantified", False):
        if "£" in str(ci) or "%" in str(ci):
            failures.append({"gate": "QA-5", "message": "Numeric impact present without quantified=true and stated inputs."})

    # QA-8: jargon without definition (simple)
    # If jargon terms appear, require a definitions section (not implemented here) — so we just fail early.
    # In practice you can soften this, but this keeps you honest.
    for term in JARGON:
        if term.lower() in as_text:
            # allow if explicitly defined (you can implement a definitions block later)
            failures.append({"gate": "QA-8", "message": f"Jargon term detected without guaranteed definition: {term}"})
            break

    return {"pass": len(failures) == 0, "failures": failures}


def render_markdown_report(report_json: Dict[str, Any], executive_summary: Dict[str, Any]) -> str:
    """
    Forces the exec template. No section, no report.
    """
    meta = report_json["meta"]
    title = f"# {meta['entity_name']} — Confirmed Tech Stack & Integration Read (Evidence-Based)\n"
    header = f"**Date:** {meta['report_date']}  \n**Scope:** {meta['scope']}\n\n"

    # Exec Summary
    exec_lines = ["## Executive Summary\n"]
    for b in executive_summary.get("confirmed_facts", []):
        exec_lines.append(f"- {b}")
    if executive_summary.get("missing_items"):
        exec_lines.append("\n**Still required to complete:**")
        for m in executive_summary["missing_items"]:
            exec_lines.append(f"- {m}")
    exec_lines.append("\n**Top actions (next 30 days):**")
    for a in executive_summary.get("top_actions_0_30", [])[:5]:
        exec_lines.append(f"- {a}")
    exec_lines.append("")

    # Stack Register
    sr = ["## Confirmed Stack Register\n"]
    sr.append("| Category | Vendor | Ownership | Evidence | Notes |")
    sr.append("|---|---|---|---|---|")
    for r in report_json["stack_register"]:
        sr.append(
            f"| {r['category']} | {r['vendor']} | {r['ownership']} | {r['evidence_level']} | {r.get('notes','')} |"
        )
    sr.append("")

    # Integration Map
    im = ["## Integration Map (Current State)\n"]
    im.append("| From | To | Data | Status | Confirmed by | Symptom if broken |")
    im.append("|---|---|---|---|---|---|")
    for row in report_json["integration_map"]:
        im.append(
            f"| {row['from']} | {row['to']} | {row['data']} | {row['status']} | {row['confirmed_by']} | {row['symptom_if_broken']} |"
        )
    im.append("")

    # Grades
    gr = ["## CEO-Aligned Grades\n"]
    gr.append("| Dimension | Grade | Why | What moves this up one grade |")
    gr.append("|---|---|---|---|")
    for g in report_json["grades"]:
        reasons = "; ".join(g.get("reasons", []))
        gr.append(f"| {g['dimension']} | {g['grade']} | {reasons} | {g['improvement_to_next_grade']} |")
    gr.append("")

    # Gaps
    gaps = ["## Gap Register\n"]
    if not report_json["gaps"]:
        gaps.append("No CEO-valid gaps could be asserted from the confirmed inputs.")
    else:
        for idx, g in enumerate(report_json["gaps"], start=1):
            gaps.append(f"### Gap {idx}: {g['gap_name']}")
            gaps.append(f"- **What is missing/broken (fact):** {g['missing_or_broken_fact']}")
            gaps.append(f"- **Where it shows up (symptom):** {g['operational_symptom']}")
            gaps.append(f"- **Decision impaired:** {g['decision_impaired']}")
            gaps.append(f"- **Risk if unchanged:** {g['risk_if_unchanged']}")
            gaps.append(f"- **Owner:** {g['owner_function']}")
            gaps.append(f"- **Close-the-gap action:** {g['close_gap_action']}")
            gaps.append("")
    gaps.append("")

    # Recommendations
    rec = ["## Recommendations (Only where eligible)\n"]
    if not report_json["recommendations"]:
        rec.append("No recommendations issued because no eligible confirmed gaps were present.")
    else:
        for r in report_json["recommendations"]:
            rec.append(f"### For: {r['gap_name']}")
            rec.append(f"- **Enable-first path:** {r['enable_first_path']}")
            rec.append("- **Options:**")
            for opt in r["tool_options"]:
                rec.append(f"  - {opt['vendor']}: {opt['why_fit']} (trade-offs: {opt['tradeoffs']})")
            rec.append("- **Selection criteria:**")
            for c in r["selection_criteria"]:
                rec.append(f"  - {c}")
            if r.get("market_risks"):
                rec.append("- **Market risks (signals):**")
                for mr in r["market_risks"]:
                    rec.append(f"  - {mr['risk_statement']} (sources: {', '.join(mr['source_refs'])})")
            rec.append("")
    rec.append("")

    # Commercial impact
    ci = report_json.get("commercial_impact", {})
    ci_md = ["## Commercial Impact\n", ci.get("statement", "Impact not quantified."), ""]

    # Next steps
    ns = ["## Next Steps\n"]
    def _render_actions(label: str, actions: List[Dict[str, Any]]) -> None:
        ns.append(f"### {label}")
        if not actions:
            ns.append("- No actions defined.")
            return
        for a in actions:
            ns.append(f"- {a['action']} — **Owner:** {a['owner_role']} — **Dependency:** {a['dependency']} — **Outcome:** {a['outcome']}")
        ns.append("")

    _render_actions("0–30 days", report_json["next_steps"]["days_0_30"])
    _render_actions("31–60 days", report_json["next_steps"]["days_31_60"])
    _render_actions("61–90 days", report_json["next_steps"]["days_61_90"])

    # Evidence & sources
    src = ["## Evidence & Sources\n"]
    src.append("- **Hotel-provided:** " + (", ".join(report_json["sources"]["hotel_provided"]) or "None provided"))
    if report_json["sources"]["public_market_signals"]:
        src.append("- **Public market signals:**")
        for s in report_json["sources"]["public_market_signals"]:
            src.append(f"  - {s['type']}: {s['title']} ({s['publisher']}, {s['date']}) — {s['url_or_ref']}")
    else:
        src.append("- **Public market signals:** None included")
    src.append("")

    return "\n".join([title, header] + exec_lines + sr + im + gr + gaps + rec + ci_md + ns + src)
