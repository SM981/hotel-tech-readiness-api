import yaml
import re
import traceback
from collections import defaultdict
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI
from pydantic import BaseModel

from scoring import score_layers
from report import opportunity_model, render_report_md

# Step 1.3+: Benchmarks + interpretation + likely-state + MD weighting + roadmap
from benchmarks import PEER_BENCHMARKS
from interpretation import interpret_score
from inference import LIKELY_STATE_BY_LAYER
from weighting import STRATEGIC_IMPORTANCE
from roadmap import ROADMAP

app = FastAPI(title="Hotel Tech Readiness API", version="0.1.0")


class AnalyzeRequest(BaseModel):
    url: str
    rooms: int | None = None
    occupancy: float | None = None
    adr: float | None = None


def label(conf: float) -> str:
    if conf >= 0.85:
        return "confirmed"
    if conf >= 0.55:
        return "probable"
    if conf > 0:
        return "possible"
    return "unknown"


def normalise_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme:
        return f"https://{url}"
    return url


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
}


async def fetch_html(url: str):
    """
    Returns (html, error_dict). Never raises.
    """
    try:
        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=30
        ) as client:
            r = await client.get(url)

            if r.status_code >= 400:
                return None, {
                    "type": "http_error",
                    "message": f"Upstream returned HTTP {r.status_code}",
                    "status_code": r.status_code
                }

            ct = r.headers.get("content-type", "")
            if "text/html" not in ct and "application/xhtml+xml" not in ct:
                return None, {
                    "type": "non_html",
                    "message": f"Unexpected content type: {ct}",
                }

            return r.text, None

    except httpx.TimeoutException:
        return None, {"type": "timeout", "message": "Upstream request timed out"}
    except httpx.RequestError as e:
        return None, {"type": "request_error", "message": str(e)}
    except Exception as e:
        return None, {"type": "unexpected_error", "message": str(e)}


def safe_regex(pattern: str, haystack: str) -> bool:
    try:
        return re.search(pattern, haystack, re.I) is not None
    except re.error:
        return False


def load_detectors():
    """
    Loads detectors.yaml safely. Never raises.
    """
    try:
        with open("detectors.yaml", "r") as f:
            data = yaml.safe_load(f) or {}
        products = data.get("products", [])
        if not isinstance(products, list):
            return []
        return products
    except Exception:
        print("ERROR loading detectors.yaml:\n" + traceback.format_exc())
        return []


def build_layer_summary(by_layer: dict) -> dict:
    """
    Converts raw detections-by-layer into an MD-friendly layer summary:
    - visibility: Detected / Not publicly visible
    - detections: list
    - likely_state + typical_risk when not visible
    - strategic_importance + rationale always
    """
    layer_order = [
        "Distribution",
        "Core Systems",
        "Guest Data & CRM",
        "Commercial Execution",
        "In-Venue Experience",
        "Operations",
        "Finance & Reporting",
    ]

    summary = {}
    for layer in layer_order:
        dets = by_layer.get(layer, []) or []
        importance, rationale = STRATEGIC_IMPORTANCE.get(layer, ("Medium", ""))

        if dets:
            summary[layer] = {
                "visibility": "Detected",
                "strategic_importance": importance,
                "importance_rationale": rationale,
                "detections": dets,
            }
        else:
            fallback = LIKELY_STATE_BY_LAYER.get(layer, {})
            summary[layer] = {
                "visibility": "Not publicly visible",
                "strategic_importance": importance,
                "importance_rationale": rationale,
                "detections": [],
                "likely_state": fallback.get("likely_state"),
                "typical_risk": fallback.get("typical_risk"),
            }

    return summary


def choose_segment(url: str) -> str:
    """
    Simple default segment selection. (Later: infer from price point, brand signals, etc.)
    For now we default to lifestyle/boutique unless the user changes it upstream.
    """
    return "lifestyle_boutique"


def fallback_response(error, model_inputs, url=None):
    """
    Always returns valid JSON. Never raises.
    """
    try:
        opp = opportunity_model(model_inputs)
    except Exception as e:
        opp = {
            "assumptions": {"rooms": 60, "occupancy": 0.72, "adr": 140},
            "annual_opportunity_gbp_range": [0, 0],
            "error": f"opportunity_model failed: {str(e)}"
        }

    segment = choose_segment(url or "")
    benchmark = PEER_BENCHMARKS.get(segment, PEER_BENCHMARKS["lifestyle_boutique"])

    return {
        "analysis": {
            "url": url,
            "detections": [],
            "scores": {
                "overall_score_0_to_100": None,
                "layer_scores": []
            },
            "benchmarks": {
                "segment": segment,
                "typical_range": list(benchmark["typical_range"]),
                "best_in_class": benchmark["best_in_class"],
                "interpretation": "Score unavailable due to limited public signals."
            },
            "layers": build_layer_summary(defaultdict(list)),
            "roadmap": ROADMAP,
            "opportunity": opp,
            "error": error,
            "notes": [
                "Public technology signals could not be processed for this website at this time.",
                "This may be due to bot protection, heavy JavaScript, rate limits, or an internal processing edge case.",
                "Confirming one internal system (PMS / booking engine / channel manager / CRM) will improve accuracy."
            ]
        },
        "report_md": (
            "# Hotel Technology & Revenue Readiness Report\n\n"
            "We couldn’t complete the automated scan just now.\n\n"
            "This does **not** indicate a problem with your systems — it’s often caused by sites restricting automated access "
            "or by a processing edge case.\n\n"
            "If you confirm your PMS, booking engine, channel manager or CRM/email platform, I’ll regenerate a full consultant-grade report.\n"
        )
    }


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """
    Hard guarantee: never throws, never returns 500.
    """
    url = normalise_url(req.url)

    model_inputs = {
        "rooms": req.rooms,
        "occupancy": req.occupancy,
        "adr": req.adr
    }

    try:
        # 1) Fetch HTML (safe)
        html, fetch_error = await fetch_html(url)
        if fetch_error:
            return fallback_response(fetch_error, model_inputs, url=url)

        # 2) Parse HTML (safe)
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(" ", strip=True)

        assets = set()
        for tag in soup.find_all(["script", "iframe", "img", "a", "link", "form"]):
            val = tag.get("src") or tag.get("href") or tag.get("action")
            if val:
                assets.add(val)

        # 3) Detect tools (safe)
        detectors = load_detectors()

        detections = []
        by_layer = defaultdict(list)

        for product in detectors:
            if not isinstance(product, dict):
                continue

            category = product.get("category") or "Unknown"
            vendor = product.get("vendor") or "Unknown"
            prod = product.get("product") or "Unknown"
            patterns = product.get("patterns", [])

            best = 0.0
            if isinstance(patterns, list):
                for pattern in patterns:
                    if not isinstance(pattern, dict):
                        continue
                    ptype = pattern.get("type")
                    value = pattern.get("value")
                    weight = float(pattern.get("weight", 0) or 0)

                    if not ptype or not value or weight <= 0:
                        continue

                    if ptype == "domain_contains":
                        if any(str(value) in a for a in assets):
                            best = max(best, weight)

                    elif ptype == "text_regex":
                        if safe_regex(str(value), html) or safe_regex(str(value), text):
                            best = max(best, weight)

            if best > 0:
                det = {
                    "vendor": vendor,
                    "product": prod,
                    "category": category,
                    "confidence": round(best, 2),
                    "label": label(best)
                }
                detections.append(det)

                # IMPORTANT: map raw detector categories into report layers if your YAML uses these
                # If your detectors.yaml already uses the layer names, this works as-is.
                by_layer[category].append(det)

        # 4) Score + opportunity (safe)
        try:
            scores = score_layers(by_layer)
        except Exception as e:
            print("ERROR in score_layers:\n" + traceback.format_exc())
            scores = {
                "overall_score_0_to_100": None,
                "layer_scores": [],
                "error": f"score_layers failed: {str(e)}"
            }

        try:
            opp = opportunity_model(model_inputs)
        except Exception as e:
            print("ERROR in opportunity_model:\n" + traceback.format_exc())
            opp = {
                "assumptions": {"rooms": 60, "occupancy": 0.72, "adr": 140},
                "annual_opportunity_gbp_range": [0, 0],
                "error": f"opportunity_model failed: {str(e)}"
            }

        # 5) Benchmarks + interpretation (Step 1.3 onwards)
        segment = choose_segment(url)
        benchmark = PEER_BENCHMARKS.get(segment, PEER_BENCHMARKS["lifestyle_boutique"])
        score_text = interpret_score(scores.get("overall_score_0_to_100"), benchmark)

        # 6) Layer summaries (likely-state + strategic importance)
        layers = build_layer_summary(by_layer)

        analysis = {
            "url": url,
            "detections": detections,
            "scores": scores,
            "benchmarks": {
                "segment": segment,
                "typical_range": list(benchmark["typical_range"]),
                "best_in_class": benchmark["best_in_class"],
                "interpretation": score_text
            },
            "layers": layers,
            "roadmap": ROADMAP,
            "opportunity": opp,
            "notes": [
                "Some hotel systems are not publicly visible and may require confirmation.",
                "Confidence labels reflect public signal strength only."
            ]
        }

        # 7) Render report (safe)
        # Recommended: update render_report_md to accept full analysis, but this works either way.
        try:
            # If you've updated report.py to render from full analysis:
            report_md = render_report_md(analysis)
        except TypeError:
            # Backwards compatible: old renderer expects only scores/opportunity
            report_md = render_report_md({
                "scores": scores,
                "opportunity": opp
            })
        except Exception as e:
            print("ERROR in render_report_md:\n" + traceback.format_exc())
            report_md = (
                "# Hotel Technology & Revenue Readiness Report\n\n"
                "Analysis completed, but report generation hit a formatting issue.\n\n"
                f"**Error:** {str(e)}\n"
            )

        return {
            "analysis": analysis,
            "report_md": report_md
        }

    except Exception as e:
        print("UNHANDLED ERROR in /analyze:\n" + traceback.format_exc())
        return fallback_response(
            {"type": "unhandled_processing_error", "message": str(e)},
            model_inputs,
            url=url
        )
