# priorities.py
from typing import Dict, Any, List


def build_exec_priorities(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produces opinionated 'Top 3' priorities based on:
    - segment inference
    - visibility/capability gap types
    - presence of tracking foundation (e.g., GTM)
    """
    segment = ((analysis or {}).get("segment_inference") or {}).get("segment", "").lower()
    gaps = ((analysis or {}).get("gaps") or {}).get("gap_summary", []) or []

    gap_by_layer = {g.get("layer"): g for g in gaps if isinstance(g, dict)}
    has_gtm = False
    detected = (analysis or {}).get("detection", {}) or {}
    tracking_layer = detected.get("tracking_attribution", {}) or {}
    tools = tracking_layer.get("tools_detected", []) or []
    for t in tools:
        if isinstance(t, dict) and (t.get("name", "") or "").lower() == "google tag manager" and t.get("confidence") == "confirmed":
            has_gtm = True

    priorities: List[Dict[str, Any]] = []

    # Priority 1: Data flow + integration health
    priorities.append({
        "title": "Map the end-to-end data flow (rooms → guest identity → marketing → reporting) and fix integration breakpoints",
        "why_now": "Integration health is the main constraint on automation, attribution accuracy, and CRM personalisation.",
        "what_good_looks_like": [
            "Single guest identity across booking engine, PMS, spa/events (where applicable), and marketing systems",
            "Clean conversion events into GA4 and accurate channel attribution for direct bookings",
            "Daily/weekly commercial dashboard fed from source systems (not spreadsheets)"
        ],
        "exec_questions": [
            "Where does guest identity fragment today (rooms vs spa vs events)?",
            "Which integrations are brittle/manual, and what fails silently?",
            "What metrics are we trusting that are actually modelled or estimated?"
        ]
    })

    # Priority 2: Tracking hygiene (if GTM present, lean into it)
    if has_gtm:
        priorities.append({
            "title": "Turn GTM into true full-funnel measurement (GA4 + booking engine events + metasearch hygiene)",
            "why_now": "You have the foundation (GTM) but without clean GA4 and conversion plumbing you cannot steer spend confidently.",
            "what_good_looks_like": [
                "GA4 configured with consistent event schema across site + booking engine",
                "Meta + paid channels receiving correct conversion signals (value + room nights if possible)",
                "Attribution model documented and stable (no constant tag churn)"
            ],
            "exec_questions": [
                "Can we reconcile marketing reporting to actual bookings without debate?",
                "Do we track abandon, step completion, and failure points in the booking journey?",
                "Is metasearch measured on incrementality or just last-click?"
            ]
        })
    else:
        priorities.append({
            "title": "Establish a measurement backbone (GTM + GA4 + conversion plumbing)",
            "why_now": "Without a measurement backbone, improvements in pricing and distribution will be hard to prove and sustain.",
            "what_good_looks_like": [
                "GTM deployed with governance and change control",
                "GA4 capturing booking-engine events reliably",
                "Marketing ROI available by channel with confidence"
            ],
            "exec_questions": [
                "What percentage of bookings are unattributed/unknown today?",
                "Which channel metrics do we not trust (and why)?"
            ]
        })

    # Priority 3: Revenue automation (segment-driven)
    if "luxury" in segment:
        priorities.append({
            "title": "Reduce manual revenue decisions: pricing guardrails + demand signals + forecast discipline",
            "why_now": "Luxury/destination hotels leak revenue through slow reaction time and human override; guardrails create consistency.",
            "what_good_looks_like": [
                "Clear pricing rules + exceptions policy",
                "Forecast cadence tied to events/pace and demand signals",
                "Documented strategy by segment (weekday corporate vs leisure peaks)"
            ],
            "exec_questions": [
                "Where are we overriding recommendations most often, and are we right?",
                "Do we have a single view of pace, pickup, and displacement across segments?"
            ]
        })
    else:
        priorities.append({
            "title": "Tighten direct mix economics: channel strategy + parity + conversion optimisation",
            "why_now": "Direct mix is the fastest path to profit; the work is usually operationally simple but requires discipline.",
            "what_good_looks_like": [
                "Defined channel roles (OTA vs metasearch vs brand search)",
                "Parity monitored and enforced",
                "Booking journey conversion improved with measurable tests"
            ],
            "exec_questions": [
                "What is our true net cost of acquisition by channel?",
                "Where do we lose customers in the booking flow?"
            ]
        })

    return {"exec_priorities_top3": priorities[:3]}
