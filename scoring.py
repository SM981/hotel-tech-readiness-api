from typing import Dict, List

LAYER_WEIGHTS = {
    "Distribution": 0.22,
    "Core Systems": 0.20,
    "Guest Data & CRM": 0.16,
    "Commercial Execution": 0.14,
    "In-Venue Experience": 0.10,
    "Operations": 0.10,
    "Finance & Reporting": 0.08,
}

def score_layers(detections_by_layer: Dict[str, List[dict]]) -> Dict:
    layer_scores = []

    for layer, weight in LAYER_WEIGHTS.items():
        detections = detections_by_layer.get(layer, [])
        if not detections:
            score = 2.0
            note = "No public signals detected; verification recommended."
        else:
            confidences = sorted(
                [d["confidence"] for d in detections], reverse=True
            )[:3]
            score = min(5.0, 2.0 + (sum(confidences) / len(confidences)) * 3)
            note = "Public signals detected with confidence scoring."

        layer_scores.append({
            "layer": layer,
            "score_0_to_5": round(score, 2),
            "notes": note
        })

    overall = sum(
        (ls["score_0_to_5"] / 5.0) * 100 * LAYER_WEIGHTS[ls["layer"]]
        for ls in layer_scores
    )

    return {
        "layer_scores": layer_scores,
        "overall_score_0_to_100": round(overall, 1)
    }
