from __future__ import annotations

from typing import Any, Dict, List


def _present_vendor(stack_rows: List[Dict[str, Any]], category: str) -> bool:
    for r in stack_rows:
        if r.get("category") == category:
            ev = r.get("evidence_level")
            vendor = (r.get("vendor") or "").strip().lower()
            if ev in {"confirmed_self_reported", "confirmed_evidence_backed"} and vendor not in {"none", "not provided"}:
                return True
    return False


def build_gap_register(
    stack_rows: List[Dict[str, Any]],
    integration_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Builds CEO-valid gaps only:
    - fact
    - symptom
    - decision impaired
    - risk
    - owner function
    - close-gap action (not a tool yet)

    No guessing. If inputs don't support the fields, do not create the gap.
    """
    gaps: List[Dict[str, Any]] = []

    # Example: Missing BI
    if not _present_vendor(stack_rows, "reporting_bi"):
        gaps.append(
            {
                "gap_name": "No central reporting view",
                "missing_or_broken_fact": "No reporting/BI tool is confirmed as in use.",
                "operational_symptom": "Leadership reporting relies on manual collation or separate system exports.",
                "decision_impaired": "Leadership cannot reliably answer performance questions from one consistent source.",
                "risk_if_unchanged": "Decisions are slower and may be disputed due to inconsistent numbers.",
                "owner_function": "leadership",
                "close_gap_action": "Confirm current reporting approach and define a single set of KPIs and data sources before selecting or enabling a reporting solution.",
                "trigger": "system_missing",
            }
        )

    # Example: Unknown integrations as a gap only if it blocks decisions (always does for CEO-level)
    unknown_links = [r for r in integration_rows if r.get("status") == "unknown_not_confirmed"]
    if unknown_links:
        gaps.append(
            {
                "gap_name": "Integration status not confirmed",
                "missing_or_broken_fact": "Core data flows have not been confirmed as active or inactive.",
                "operational_symptom": "Teams may be rekeying data or reconciling reports, but this cannot be stated until confirmed.",
                "decision_impaired": "Leadership cannot determine where data breaks and where manual effort is being applied.",
                "risk_if_unchanged": "You risk investing in new tools before confirming what can be enabled within the current stack.",
                "owner_function": "leadership",
                "close_gap_action": "Confirm each core integration as Active or Not active, and document where manual work occurs today.",
                "trigger": "process_gap_confirmed",
            }
        )

    # Example: Missing RMS
    if not _present_vendor(stack_rows, "rms"):
        gaps.append(
            {
                "gap_name": "No confirmed revenue management system",
                "missing_or_broken_fact": "No RMS is confirmed as in use.",
                "operational_symptom": "Pricing and forecasting may be handled manually or within PMS tools; configuration is not confirmed.",
                "decision_impaired": "Revenue leadership cannot confirm whether pricing decisions are automated, consistent, and auditable.",
                "risk_if_unchanged": "Pricing may become reactive and inconsistent across properties, particularly in high-demand periods.",
                "owner_function": "revenue",
                "close_gap_action": "Confirm how pricing decisions are made today and whether the current PMS/channel tooling provides sufficient automation before adding an RMS.",
                "trigger": "system_missing",
            }
        )

    return gaps


def build_recommendations(
    gaps: List[Dict[str, Any]],
    stack_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Recommendations are ONLY allowed when:
    - trigger is system_missing OR integration_not_active OR process_gap_confirmed AND
    - the gap is explicitly confirmed (we use trigger values from gaps)
    """
    recs: List[Dict[str, Any]] = []

    for g in gaps:
        trigger = g.get("trigger")
        if trigger not in {"system_missing", "integration_not_active", "process_gap_confirmed"}:
            continue

        name = g["gap_name"]

        # Keep options generic until you add vendor catalog + market sources.
        if name == "No central reporting view":
            recs.append(
                {
                    "gap_name": name,
                    "enable_first_path": "Confirm whether existing finance or PMS reporting can meet the KPI set before introducing a new BI layer.",
                    "tool_options": [
                        {"vendor": "Microsoft Power BI", "why_fit": "Commonly used for multi-source dashboards across finance and operations.", "tradeoffs": "Requires data modelling and ongoing governance."},
                        {"vendor": "Tableau", "why_fit": "Strong visualisation and enterprise reporting capability.", "tradeoffs": "Licensing and implementation effort can be higher."},
                    ],
                    "selection_criteria": [
                        "Can it combine PMS, channel, finance, and guest data sources?",
                        "Who will own data governance and KPI definitions?",
                        "How quickly can leadership get a weekly performance pack from it?",
                    ],
                    "market_risks": [],
                }
            )

        if name == "No confirmed revenue management system":
            recs.append(
                {
                    "gap_name": name,
                    "enable_first_path": "Confirm whether your PMS or existing commercial tooling already supports rate automation before adding a standalone RMS.",
                    "tool_options": [
                        {"vendor": "IDeaS", "why_fit": "Widely used RMS in hotels for automated pricing and forecasting.", "tradeoffs": "Implementation quality depends on data hygiene and process adoption."},
                        {"vendor": "Duetto", "why_fit": "Cloud RMS focused on pricing and demand forecasting workflows.", "tradeoffs": "Requires strong integration discipline to avoid manual overrides."},
                    ],
                    "selection_criteria": [
                        "Integration support with your PMS and channel manager",
                        "Ability to support group-level governance and property-level execution",
                        "Clarity of audit trail for pricing decisions",
                    ],
                    "market_risks": [],
                }
            )

        if name == "Integration status not confirmed":
            # This is a process recommendation rather than a tool push.
            recs.append(
                {
                    "gap_name": name,
                    "enable_first_path": "Run a 30-minute confirmation workshop: confirm each flow as Active or Not active and document any manual steps.",
                    "tool_options": [
                        {"vendor": "Integration audit worksheet", "why_fit": "Fastest path to certainty without buying new systems.", "tradeoffs": "Requires stakeholder time and accurate answers."},
                        {"vendor": "iPaaS (only if required)", "why_fit": "Consider only if confirmed integrations cannot be activated natively.", "tradeoffs": "Adds integration complexity and ongoing dependency."},
                    ],
                    "selection_criteria": [
                        "Can native integrations be enabled first?",
                        "Is there a clear owner for integration governance?",
                        "Is the integration need repeatable across properties?",
                    ],
                    "market_risks": [],
                }
            )

    return recs
