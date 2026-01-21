from __future__ import annotations

from typing import Any, Dict, List


def _grade_from_score(score: int) -> str:
    # 0–20 -> E, 21–40 -> D, 41–60 -> C, 61–80 -> B, 81–100 -> A
    if score >= 81:
        return "A"
    if score >= 61:
        return "B"
    if score >= 41:
        return "C"
    if score >= 21:
        return "D"
    return "E"


def _count_integration_status(integration_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"active": 0, "not_active": 0, "unknown": 0}
    for r in integration_rows:
        s = r.get("status")
        if s == "active_confirmed":
            counts["active"] += 1
        elif s == "not_active_confirmed":
            counts["not_active"] += 1
        else:
            counts["unknown"] += 1
    return counts


def _has_category(stack_rows: List[Dict[str, Any]], category: str) -> bool:
    # Any vendor not None/Not provided counts as present
    for r in stack_rows:
        if r.get("category") == category:
            v = (r.get("vendor") or "").strip().lower()
            ev = r.get("evidence_level")
            if ev in {"confirmed_self_reported", "confirmed_evidence_backed"} and v not in {"none", "not provided"}:
                return True
    return False


def compute_grades(stack_rows: List[Dict[str, Any]], integration_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deterministic grading only.
    - No benchmarks
    - No external assumptions
    - Uses: presence of core systems + integration status certainty
    """
    counts = _count_integration_status(integration_rows)
    total_links = max(1, len(integration_rows))

    # Decision support: penalise unknown integrations and missing BI
    decision_score = 100
    decision_score -= int((counts["unknown"] / total_links) * 60)
    if not _has_category(stack_rows, "reporting_bi"):
        decision_score -= 20

    # Data flow integrity: reward active links, penalise not active/unknown
    flow_score = 100
    flow_score -= counts["unknown"] * 8
    flow_score -= counts["not_active"] * 12
    flow_score = max(0, min(100, flow_score))

    # Commercial leverage: RMS + CRM + Email presence (not their quality)
    leverage_score = 40
    if _has_category(stack_rows, "rms"):
        leverage_score += 20
    if _has_category(stack_rows, "crm_guest_db"):
        leverage_score += 20
    if _has_category(stack_rows, "email_lifecycle"):
        leverage_score += 20
    leverage_score = max(0, min(100, leverage_score))

    # Operational friction: task tools presence + unknown integrations
    friction_score = 80
    if not _has_category(stack_rows, "housekeeping_maintenance"):
        friction_score -= 20
    friction_score -= int((counts["unknown"] / total_links) * 30)
    friction_score = max(0, min(100, friction_score))

    # Scalability/resilience: ownership unknown / high unknown integration count penalises
    resilience_score = 90
    resilience_score -= counts["unknown"] * 6
    resilience_score = max(0, min(100, resilience_score))

    def row(dim: str, score: int, reasons: List[str], improve: str) -> Dict[str, Any]:
        return {
            "dimension": dim,
            "grade": _grade_from_score(score),
            "reasons": reasons,
            "improvement_to_next_grade": improve,
        }

    return [
        row(
            "decision_support",
            decision_score,
            reasons=[
                "Grades are based on confirmed stack presence and confirmed integration statuses only.",
                f"Integrations not yet confirmed: {counts['unknown']} out of {total_links}.",
            ],
            improve="Confirm integration statuses and ensure leadership reporting is produced from a consistent data source.",
        ),
        row(
            "data_flow_integrity",
            flow_score,
            reasons=[
                f"Active links confirmed: {counts['active']}.",
                f"Links not active: {counts['not_active']}.",
                f"Links not confirmed: {counts['unknown']}.",
            ],
            improve="Confirm each core system data flow and activate integrations where data is currently rekeyed or reconciled manually.",
        ),
        row(
            "commercial_leverage",
            leverage_score,
            reasons=[
                "This grade reflects presence of commercial capability tools only (not their configuration).",
                "Higher scores require confirmed RMS + CRM + lifecycle marketing capability.",
            ],
            improve="Confirm and connect pricing, guest data, and lifecycle communications so commercial actions are measurable and repeatable.",
        ),
        row(
            "operational_friction",
            friction_score,
            reasons=[
                "This grade reflects likely manual burden implied by missing operational tooling and unconfirmed flows.",
            ],
            improve="Confirm operational workflow tooling and remove duplicated entry points between systems.",
        ),
        row(
            "scalability_resilience",
            resilience_score,
            reasons=[
                "This grade reflects how repeatable the stack is likely to be, based on confirmation completeness.",
            ],
            improve="Standardise system ownership (group vs property), document integrations, and reduce reliance on individual workarounds.",
        ),
    ]
