from typing import Any, Dict, List, Tuple

LAYER_WEIGHTS: Dict[str, float] = {
    "Distribution": 0.22,
    "Core Systems": 0.20,
    "Guest Data & CRM": 0.16,
    "Commercial Execution": 0.14,
    "In-Venue Experience": 0.10,
    "Operations": 0.10,
    "Finance & Reporting": 0.08,
}

# Scoring model:
# - Base score reflects "capability likely exists" in hotels, but integration maturity unknown.
# - Observed public signals raise the score.
# - Customer-confirmed signals raise the score further (highest confidence).
# - We never claim "absence"; we score maturity/visibility.
BASELINE_SCORE_0_TO_5 = 2.4

# Source multipliers
SRC_MULTIPLIER = {
    "customer_confirmed": 1.00,  # treat as strongest signal
    "public_signal": 0.85,       # strong but limited to what’s visible
    "inferred": 0.55,            # weaker: plausible but not proven
    "unknown": 0.40,             # fallback if source missing
}

# Cap how many detections per layer influence the score
TOP_N = 4


def _safe_list(x: Any) -> List[Any]:
    return x if isinstance(x, list) else []


def _detection_strength(det: Dict[str, Any]) -> float:
    """
    Compute a single detection strength in [0, 1.0] combining:
    - confidence (0..1) from detector match
    - source multiplier (customer_confirmed > public_signal > inferred)
    """
    if not isinstance(det, dict):
        return 0.0

    conf = det.get("confidence")
    try:
        conf_f = float(conf)
    except Exception:
        conf_f = 0.0

    src = (det.get("source") or "unknown").strip().lower()
    mult = SRC_MULTIPLIER.get(src, SRC_MULTIPLIER["unknown"])

    # Clamp confidence defensively
    if conf_f < 0:
        conf_f = 0.0
    if conf_f > 1:
        conf_f = 1.0

    return conf_f * mult


def _layer_score_from_detections(detections: List[Dict[str, Any]]) -> Tuple[float, Dict[str, Any]]:
    """
    Returns (score_0_to_5, diagnostics)
    """
    dets = [d for d in _safe_list(detections) if isinstance(d, dict)]
    if not dets:
        return BASELINE_SCORE_0_TO_5, {
            "state": "inferred_baseline",
            "explanation": "No direct evidence observed for this layer in public signals; score reflects baseline capability typically present in hotels.",
            "top_signals": [],
        }

    strengths = sorted([_detection_strength(d) for d in dets], reverse=True)
    top_strengths = strengths[:TOP_N]
    avg_strength = sum(top_strengths) / max(1, len(top_strengths))

    # Convert avg_strength (0..1) into uplift (0..~2.4)
    # Keeps score within [BASELINE, 5.0] and prevents over-scoring due to noisy tags.
    uplift = avg_strength * 2.6
    score = BASELINE_SCORE_0_TO_5 + uplift
    if score > 5.0:
        score = 5.0

    # Diagnostics: show top detections (vendor/product/source/label)
    top_dets = sorted(
        dets,
        key=lambda d: _detection_strength(d),
        reverse=True,
    )[:TOP_N]
    top_signals = []
    for d in top_dets:
        top_signals.append({
            "vendor": d.get("vendor"),
            "product": d.get("product"),
            "category": d.get("category"),
            "confidence": d.get("confidence"),
            "label": d.get("label"),
            "source": d.get("source"),
        })

    # Determine state label
    has_confirmed = any((d.get("source") == "customer_confirmed") for d in dets)
    state = "confirmed" if has_confirmed else "observed"

    return round(score, 2), {
        "state": state,
        "explanation": "Evidence observed for this layer; score reflects public visibility and signal strength.",
        "top_signals": top_signals,
    }


def score_layers(detections_by_layer: Dict[str, List[dict]]) -> Dict[str, Any]:
    """
    Returns:
      {
        "layer_scores": [
          {"layer": ..., "score": x, "out_of": 5, "weight": w, "state": ..., "notes": ..., "signals": [...]},
          ...
        ],
        "overall_score_0_to_100": ...
      }

    Compatible with report renderers expecting either:
    - layer_scores[*].score + out_of
    """
    layer_scores: List[Dict[str, Any]] = []

    for layer, weight in LAYER_WEIGHTS.items():
        detections = detections_by_layer.get(layer, []) or []
        score_0_to_5, diag = _layer_score_from_detections(detections)

        layer_scores.append({
            "layer": layer,
            "score": score_0_to_5,
            "out_of": 5,
            "weight": weight,
            "state": diag.get("state"),
            "notes": diag.get("explanation"),
            "signals": diag.get("top_signals", []),
        })

    overall = 0.0
    for ls in layer_scores:
        try:
            s = float(ls.get("score", 0.0))
            out_of = float(ls.get("out_of", 5.0))
            w = float(ls.get("weight", 0.0))
        except Exception:
            continue

        if out_of <= 0:
            continue
        overall += (s / out_of) * 100.0 * w

    return {
        "layer_scores": layer_scores,
        "overall_score_0_to_100": round(overall, 1),
    }
