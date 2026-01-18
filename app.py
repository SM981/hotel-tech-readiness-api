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


with open("detectors.yaml", "r") as f:
    DETECTORS = yaml.safe_load(f)["products"]


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
    try:
        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=30
        ) as client:
            r = await client.get(url)
            r.raise_for_status()

            ct = r.headers.get("content-type", "")
            if "text/html" not in ct:
                return None, {
                    "type": "non_html",
                    "message": f"Unexpected content type: {ct}"
                }

            return r.text, None

    except httpx.HTTPStatusError as e:
        return None, {
            "type": "http_error",
            "message": f"Upstream returned HTTP {e.response.status_code}"
        }
    except httpx.TimeoutException:
        return None, {
            "type": "timeout",
            "message": "Upstream request timed out"
        }
    except httpx.RequestError as e:
        return None, {
            "type": "request_error",
            "message": str(e)
        }


def fallback_response(error, model_inputs):
    opp = opportunity_model(model_inputs)

    return {
        "analysis": {
            "detections": [],
            "scores": {
                "overall_score_0_to_100": None,
                "layer_scores": []
            },
            "opportunity": opp,
            "error": error,
            "notes": [
                "Public technology signals could not be retrieved from this site.",
                "This commonly occurs on enterprise or brand websites that restrict automated access.",
                "A short manual verification will produce a more accurate assessment."
            ]
        },
        "report_md": (
            "# Hotel Technology & Revenue Readiness Report\n\n"
            "We couldn’t retrieve public technology signals from the website just now.\n\n"
            "This does **not** indicate a problem with your systems. Many hotel brands "
            "restrict automated access or require JavaScript rendering.\n\n"
            "## What happens next\n"
            "- If you share known systems (PMS, booking engine, channel manager, CRM, RMS), "
            "I’ll produce a full consultant-grade report.\n"
            "- You can also confirm rooms, occupancy, and ADR to refine opportunity ranges.\n\n"
            "## Methodology & disclosure\n"
            "- Public website signals only (where accessible)\n"
            "- No access to private systems or guest data\n"
            "- Findings should be verified\n"
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

    html, error = await fetch_html(url)
    if error:
        return fallback_response(error, model_inputs)

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

            if ptype == "domain_contains":
                if any(value in a for a in assets):
                    best = max(best, weight)

            elif ptype == "text_regex":
                if re.search(value, html, re.I) or re.search(value, text, re.I):
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

    scores = score_layers(by_layer)
    opp = opportunity_model(model_inputs)

    analysis = {
        "url": url,
        "detections": detections,
        "scores": scores,
        "opportunity": opp,
        "notes": [
            "Some hotel systems do not expose public signals and may appear as Unknown.",
            "Confidence labels reflect strength of public evidence only."
        ]
    }

    report_md = render_report_md({
        "scores": scores,
        "opportunity": opp
    })

    return {
        "analysis": analysis,
        "report_md": report_md
    }
