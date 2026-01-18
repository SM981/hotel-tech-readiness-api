import yaml
import re
from fastapi import FastAPI
from pydantic import BaseModel
from bs4 import BeautifulSoup
import httpx
from collections import defaultdict

from scoring import score_layers
from report import opportunity_model, render_report_md

app = FastAPI(title="Hotel Tech Readiness API")

class AnalyzeRequest(BaseModel):
    url: str
    rooms: int | None = None
    occupancy: float | None = None
    adr: float | None = None

with open("detectors.yaml", "r") as f:
    DETECTORS = yaml.safe_load(f)["products"]

def label(conf):
    if conf >= 0.85: return "confirmed"
    if conf >= 0.55: return "probable"
    if conf > 0: return "possible"
    return "unknown"

@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    async with httpx.AsyncClient() as client:
        r = await client.get(req.url, follow_redirects=True, timeout=20)
        html = r.text

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    domains = set(tag.get("src", "") for tag in soup.find_all("script") if tag.get("src"))

    detections = []
    by_layer = defaultdict(list)

    for product in DETECTORS:
        best = 0
        for pattern in product["patterns"]:
            if pattern["type"] == "domain_contains":
                if any(pattern["value"] in d for d in domains):
                    best = max(best, pattern["weight"])
            elif pattern["type"] == "text_regex":
                if re.search(pattern["value"], text, re.I):
                    best = max(best, pattern["weight"])

        if best > 0:
            det = {
                "vendor": product["vendor"],
                "product": product["product"],
                "confidence": best,
                "label": label(best)
            }
            detections.append(det)
            by_layer[product["category"]].append(det)

    scores = score_layers(by_layer)
    opp = opportunity_model({
        "rooms": req.rooms,
        "occupancy": req.occupancy,
        "adr": req.adr
    })

    analysis = {
        "detections": detections,
        "scores": scores,
        "opportunity": opp
    }

    report_md = render_report_md({
        "scores": scores,
        "opportunity": opp
    })

    return {
        "analysis": analysis,
        "report_md": report_md
    }
