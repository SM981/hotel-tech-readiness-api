# segment.py
from dataclasses import dataclass
from typing import Dict, Any, List


@dataclass
class SegmentInference:
    segment: str
    confidence: str
    evidence: List[str]
    implications: List[str]


LUXURY_CUES = [
    "grand", "luxury", "five-star", "5-star", "spa", "afternoon tea",
    "suite", "heritage", "historic", "fine dining", "champagne"
]

DESTINATION_CUES = [
    "york", "cathedral", "city centre", "city center", "landmark",
    "rail", "station", "walk to", "minutes from"
]


def infer_hotel_segment(public_text: str, url: str = "") -> SegmentInference:
    """
    Very light heuristic inference using publicly available page text.
    Keep it conservative and explainable.
    """
    text = (public_text or "").lower()
    u = (url or "").lower()

    evidence = []
    luxury_hits = [c for c in LUXURY_CUES if c in text]
    dest_hits = [c for c in DESTINATION_CUES if c in text or c in u]

    if luxury_hits:
        evidence.append(f"Luxury cues: {', '.join(sorted(set(luxury_hits))[:6])}")
    if dest_hits:
        evidence.append(f"Destination cues: {', '.join(sorted(set(dest_hits))[:6])}")

    if luxury_hits and dest_hits:
        segment = "Luxury destination hotel"
        confidence = "Medium"
        implications = [
            "Likely multi-department revenue centres (rooms + F&B + spa + events) → guest data fragmentation risk is high.",
            "Attribution and channel mix typically more complex → GA4 + booking-engine event hygiene is a common leak.",
            "Integration health matters more than tool count → prioritise data flow mapping before vendor changes."
        ]
    elif luxury_hits:
        segment = "Luxury independent hotel"
        confidence = "Low–Medium"
        implications = [
            "Premium positioning → direct booking and repeat behaviour are key levers.",
            "CRM orchestration and identity resolution typically under-utilised.",
            "Integration health is usually the maturity constraint."
        ]
    else:
        segment = "Independent hotel"
        confidence = "Low"
        implications = [
            "Benchmark context should be broad; focus on foundational tracking + distribution hygiene first."
        ]

    if not evidence:
        evidence = ["No strong segment cues detected in sampled public text."]

    return SegmentInference(
        segment=segment,
        confidence=confidence,
        evidence=evidence,
        implications=implications
    )


def segment_to_dict(s: SegmentInference) -> Dict[str, Any]:
    return {
        "segment": s.segment,
        "confidence": s.confidence,
        "evidence": s.evidence,
        "implications": s.implications
    }
