from __future__ import annotations

from typing import Any, Dict, List


OWNER_ROLE_MAP = {
    "revenue": "Commercial / Revenue Director",
    "marketing": "Marketing Director",
    "operations": "Operations Director",
    "finance": "Finance Director",
    "leadership": "GM / CEO",
    "it": "IT Lead",
}


def _severity(gap: Dict[str, Any]) -> int:
    """
    Deterministic severity based on:
    - decision impaired presence (always required)
    - risk wording length/clarity (proxy, not sentiment)
    Kept intentionally simple and transparent.
    """
    score = 50
    if gap.get("trigger") in {"system_missing", "integration_not_active"}:
        score += 20
    if "cannot" in (gap.get("decision_impaired", "").lower()):
        score += 10
    if "risk" in (gap.get("risk_if_unchanged", "").lower()):
        score += 5
    return min(100, score)


def build_next_steps(gaps: List[Dict[str, Any]], recommendations: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Sort gaps by severity, highest first
    ranked = sorted(gaps, key=_severity, reverse=True)

    actions_0_30: List[Dict[str, Any]] = []
    actions_31_60: List[Dict[str, Any]] = []
    actions_61_90: List[Dict[str, Any]] = []

    for g in ranked:
        owner_fn = g.get("owner_function", "leadership")
        owner_role = OWNER_ROLE_MAP.get(owner_fn, "GM / CEO")

        # Convert each gap into actions that close uncertainty first, then enable, then consider buying.
        base_action = {
            "action": g["close_gap_action"],
            "owner_role": owner_role,
            "dependency": "Stakeholder confirmation",
            "outcome": "Gap is closed with an evidence-backed decision.",
        }

        # Place unknown/confirmation-heavy actions in 0–30
        if g.get("gap_name") in {"Integration status not confirmed"}:
            actions_0_30.append(base_action)
            continue

        # System missing: confirm enable-first then shortlist
        if g.get("trigger") == "system_missing":
            actions_0_30.append(base_action)
            actions_31_60.append(
                {
                    "action": f"Define requirements and shortlist options for: {g['gap_name']}",
                    "owner_role": owner_role,
                    "dependency": "Confirmed requirements",
                    "outcome": "A short list is selected based on fit and integration needs.",
                }
            )
            actions_61_90.append(
                {
                    "action": f"Pilot or implement chosen approach for: {g['gap_name']}",
                    "owner_role": owner_role,
                    "dependency": "Vendor selection and implementation plan",
                    "outcome": "Capability is live and measured operationally.",
                }
            )
            continue

        # Default placement
        actions_0_30.append(base_action)

    # Cap list lengths for exec readability
    def cap(xs: List[Dict[str, Any]], n: int = 6) -> List[Dict[str, Any]]:
        return xs[:n]

    return {
        "days_0_30": cap(actions_0_30),
        "days_31_60": cap(actions_31_60),
        "days_61_90": cap(actions_61_90),
    }
