from __future__ import annotations

from typing import Any, Dict, List


def build_market_signal_stub(vendor: str, category: str) -> Dict[str, Any]:
    """
    This module is intentionally conservative:
    - It does NOT assert facts about any specific hotel.
    - It only stores 'market signals' that you can cite later.

    In production, you would populate this via curated sources (reviews, forums, vendor docs)
    gathered outside the model, then pass them in.

    Output is a neutral container, not a judgement.
    """
    return {
        "vendor": vendor,
        "category": category,
        "signals": [],  # list of {risk_statement, source_refs}
        "notes": "Market signals are not facts. They are used only to flag common implementation pitfalls.",
    }


def attach_market_risks_to_recommendations(
    recommendations: List[Dict[str, Any]],
    market_signal_index: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Optionally attach market risks (signals) to recommendations.
    market_signal_index keyed by vendor name.
    """
    for r in recommendations:
        for opt in r.get("tool_options", []):
            vendor = opt.get("vendor")
            if not vendor:
                continue
            ms = market_signal_index.get(vendor)
            if ms and ms.get("signals"):
                # Attach to market_risks list in the report schema format
                r.setdefault("market_risks", [])
                for s in ms["signals"]:
                    r["market_risks"].append(
                        {"risk_statement": s["risk_statement"], "source_refs": s["source_refs"]}
                    )
    return recommendations
