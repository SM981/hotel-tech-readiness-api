import yaml
import re
from collections import defaultdict
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI
from pydantic import BaseModel

from scoring import score_layers
from report import opportunity_model, render_report_md

app = FastAPI(title="Hotel Tech Readiness API", version="0.1.0")


class AnalyzeRequest(BaseModel):
    url: str
    rooms: int | None = None
    occupancy: float | None = None
    adr: float | None = None


# Load detector definitions safely
with open("detectors.yaml", "r") as f:
    DETECTORS = yaml.safe_load(f).get("products", [])


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
    Fetches HTML safely.
    Returns (html, error_dict). Exactly one will be None.
    Never raises.
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
                    "message": f"Upstream returned HTTP {r.status_code}"
                }

            ct = r.headers.get("content-type", "")
            if "text/html" not in ct and "application/xhtml+xml" not in ct:
                return None, {
                    "type": "non_html",
                    "message": f"Unexpected content type: {ct}"
                }

            return r.text, None

    except httpx.TimeoutException:
        return None, {"type": "timeout", "message": "Upstream request timed out"}
    except httpx.RequestError as e:
        return None, {"type": "request_error", "message": str(e)}
    except Exception as e:
        return None, {"type": "unexpected_error", "message": str(e)}


def safe_regex(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text, re.I) is not None
    except re.error:
        return False


def fallback_response(error, model_inputs):
    opp = opportunity_model(model_inputs)

    return {
        "analysis": {
            "url": None,
            "detections": [],
            "scores": {
                "overall_score_0_to_100": None,
                "layer_scores": []
            },
            "opportunity": opp,
            "error": error,
            "notes": [
                "Public technology signals could not be retrieved from this website.",
                "This is common for sites protected by bot mitigation or heavy JavaScript.",
                "Confirming one internal system will improve accuracy."
            ]
        },
        "report_md": (
            "# Hotel Technology & Revenue Readiness Report\n\n"
            "We couldn’t retrieve public technology signals from the website just now.\n\n"
            "This does **not** indicate a problem with your systems. Many hotel brands "
            "restrict automated access.\n\n"
            "Confirming a booking engine, PMS, or CRM will produce a full consultant-grade report."
        )
    }


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    url = normalise_url(req.url)

    model_inputs = {
        "rooms": req.rooms,
        "occupancy": req.occupancy,
        "adr": req.adr
    }

    # 1) Fetch HTML safely
    html, error = await fetch_html(url)
    if error:
        return fallback_response(error, model_inputs)

    try:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(" ", strip=True)

        assets = set()
        for tag in soup.find_all(["script", "iframe", "img", "a", "link"]):
            src = tag.get("src") or tag.get("href")
            if src:
                assets.add(src)

        detections = []
        by_layer = defaultdict(list)

        for product in DETECTORS:
            best = 0.0

            for pattern in product.get("patterns", []):
                ptype = pattern.get("type")
                value = pattern.get("value")
                weight = float(pattern.get("weight", 0))

                if not ptype or not value or weight <= 0:
                    continue

                if ptype == "domain_contains":
                    if any(value in a for a in assets):
                        best = max(best, weight)

                elif ptype == "text_regex":
                    if safe_regex(value, html) or safe_regex(value, text):
                        best = max(best, weight)

            if best > 0:
                det = {
                    "vendor": product.get("vendor"),
                    "product": product.get("product"),
                    "category": product.get("category"),
                    "confidence": round(best, 2),
                    "label": label(best)
                }
                detections.append(det)
                by_layer[product["category"]].append(det)

        # 2) Score safely
        try:
            scores = score_layers(by_layer)
        except Exception as e:
            scores = {
                "overall_score_0_to_100": None,
                "layer_scores": [],
                "error": str(e)
            }

        # 3) Opportunity safely (defaults handled in report.py)
        try:
            opp = opportunity_model(model_inputs)
        except Exception as e:
            opp = {
                "assumptions": {"rooms": 60, "occupancy": 0.72, "adr": 140},
                "annual_opportunity_gbp_range": [0, 0],
                "error": str(e)
            }

        analysis = {
            "url": url,
            "detections": detections,
            "scores": scores,
            "opportunity": opp,
            "notes": [
                "Some hotel systems are not publicly visible and may require confirmation.",
                "Confidence labels reflect public signal strength only."
            ]
        }

        # 4) Render report safely (never crash)
        try:
            report_md = render_report_md({
                "scores": scores,
                "opportunity": opp
            })
        except Exception as e:
            report_md = (
                "# Hotel Technology & Revenue Readiness Report\n\n"
                "Analysis completed, but report formatting failed.\n\n"
                f"Error: {str(e)}"
            )

        return {
            "analysis": analysis,
            "report_md": report_md
        }

    except Exception as e:
        # Absolute last line of defence — never return 500
        return fallback_response(
            {"type": "processing_error", "message": str(e)},
            model_inputs
        )
