import re
import traceback
import logging
from dataclasses import dataclass
from functools import lru_cache
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

import yaml
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI
from pydantic import BaseModel, Field

from scoring import score_layers
from report import opportunity_model, render_report_md

# Step 1.3+: Benchmarks + interpretation + likely-state + MD weighting + roadmap
from benchmarks import PEER_BENCHMARKS
from interpretation import interpret_score
from inference import LIKELY_STATE_BY_LAYER
from weighting import STRATEGIC_IMPORTANCE
from roadmap import ROADMAP

# ----------------------------
# Logging
# ----------------------------
logger = logging.getLogger("hotel_tech_readiness")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Hotel Tech Readiness API", version="0.2.0")

# ----------------------------
# OpenAPI Models (important for GPT Actions)
# ----------------------------
class AnalyzeRequest(BaseModel):
    url: str
    rooms: int | None = None
    occupancy: float | None = None
    adr: float | None = None


class AnalyzeResponse(BaseModel):
    analysis: Dict[str, Any] = Field(
        ...,
        description="Full structured analysis object (scores, detections, benchmarks, layers, roadmap, etc.).",
    )
    report_md: str = Field(..., description="Consultant-grade report in Markdown.")


# ----------------------------
# Utilities
# ----------------------------
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


async def fetch_html(url: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Returns (html, error_dict). Never raises.
    """
    try:
        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS, follow_redirects=True, timeout=30
        ) as client:
            r = await client.get(url)

            if r.status_code >= 400:
                return None, {
                    "type": "http_error",
                    "message": f"Upstream returned HTTP {r.status_code}",
                    "status_code": r.status_code,
                }

            ct = (r.headers.get("content-type") or "").lower()
            if ("text/html" not in ct) and ("application/xhtml+xml" not in ct):
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


@lru_cache(maxsize=1)
def load_detectors() -> List[Dict[str, Any]]:
    """
    Loads detectors.yaml safely. Cached. Never raises.
    """
    try:
        with open("detectors.yaml", "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        products = data.get("products", [])
        if not isinstance(products, list):
            return []
        # Keep only dict items
        return [p for p in products if isinstance(p, dict)]
    except Exception:
        logger.error("ERROR loading detectors.yaml:\n%s", traceback.format_exc())
        return []


# ----------------------------
# Layer mapping
# (lets your detectors.yaml use flexible categories while keeping a consistent report structure)
# ----------------------------
CANONICAL_LAYER_ORDER = [
    "Distribution",
    "Core Systems",
    "Guest Data & CRM",
    "Commercial Execution",
    "In-Venue Experience",
    "Operations",
    "Finance & Reporting",
]

# Common synonyms / detector categories -> canonical report layers
CATEGORY_TO_LAYER = {
    # Distribution
    "distribution": "Distribution",
    "crs": "Distribution",
    "channel_manager": "Distribution",
    "channel manager": "Distribution",
    "ota": "Distribution",
    "metasearch": "Distribution",
    "booking engine": "Distribution",
    "booking_engine": "Distribution",

    # Core Systems
    "pms": "Core Systems",
    "rms": "Core Systems",
    "property management": "Core Systems",
    "revenue management": "Core Systems",
    "core systems": "Core Systems",

    # Guest data
    "crm": "Guest Data & CRM",
    "email": "Guest Data & CRM",
    "marketing automation": "Guest Data & CRM",
    "guest data": "Guest Data & CRM",
    "loyalty": "Guest Data & CRM",

    # Commercial execution / tracking
    "tracking": "Commercial Execution",
    "analytics": "Commercial Execution",
    "attribution": "Commercial Execution",
    "tag manager": "Commercial Execution",
    "advertising": "Commercial Execution",
    "commercial execution": "Commercial Execution",

    # In-venue experience
    "in-venue": "In-Venue Experience",
    "in venue": "In-Venue Experience",
    "guest messaging": "In-Venue Experience",
    "digital check-in": "In-Venue Experience",
    "upsell": "In-Venue Experience",
    "wifi": "In-Venue Experience",

    # Ops
    "operations": "Operations",
    "housekeeping": "Operations",
    "maintenance": "Operations",
    "task management": "Operations",
    "workforce": "Operations",

    # Finance
    "finance": "Finance & Reporting",
    "accounting": "Finance & Reporting",
    "bi": "Finance & Reporting",
    "reporting": "Finance & Reporting",
    "dashboard": "Finance & Reporting",
    "finance & reporting": "Finance & Reporting",
}

def map_category_to_layer(category: str) -> str:
    c = (category or "").strip().lower()
    if not c:
        return "Commercial Execution"  # safest default for unknown web signals
    return CATEGORY_TO_LAYER.get(c, category) if category in CANONICAL_LAYER_ORDER else CATEGORY_TO_LAYER.get(c, "Commercial Execution")


# ----------------------------
# MD-grade report enhancers (segment inference + gap classification + exec priorities)
# Self-contained so you can copy/paste app.py alone.
# ----------------------------
@dataclass
class SegmentInference:
    segment: str
    confidence: str
    evidence: List[str]
    implications: List[str]


_LUXURY_CUES = [
    "grand", "luxury", "five-star", "5-star", "spa", "afternoon tea",
    "suite", "heritage", "historic", "fine dining", "champagne",
]
_DESTINATION_CUES = [
    "york", "cathedral", "city centre", "city center", "landmark",
    "rail", "station", "minutes from", "walk to",
]

def infer_hotel_segment(public_text: str, url: str = "") -> Dict[str, Any]:
    """
    Conservative, explainable segment inference from public text signals.
    """
    text = (public_text or "").lower()
    u = (url or "").lower()

    evidence: List[str] = []
    luxury_hits = [c for c in _LUXURY_CUES if c in text]
    dest_hits = [c for c in _DESTINATION_CUES if (c in text) or (c in u)]

    if luxury_hits:
        evidence.append(f"Luxury cues: {', '.join(sorted(set(luxury_hits))[:6])}")
    if dest_hits:
        evidence.append(f"Destination cues: {', '.join(sorted(set(dest_hits))[:6])}")

    if luxury_hits and dest_hits:
        segment = "Luxury destination hotel"
        confidence = "Medium"
        implications = [
            "Likely multiple revenue centres (rooms + F&B + spa + events) → guest data fragmentation risk is high.",
            "Attribution and channel mix typically more complex → booking-engine conversion plumbing is a common leak.",
            "Integration health matters more than tool count → prioritise data flow mapping before vendor changes.",
        ]
    elif luxury_hits:
        segment = "Luxury independent hotel"
        confidence = "Low–Medium"
        implications = [
            "Premium positioning → direct mix and repeat behaviour are high-leverage commercial levers.",
            "CRM orchestration and identity resolution are often under-utilised.",
            "Integration health is usually the maturity constraint, not vendor choice.",
        ]
    else:
        segment = "Independent hotel"
        confidence = "Low"
        implications = [
            "Benchmark context should be broad; focus on foundational tracking + distribution hygiene first.",
        ]

    if not evidence:
        evidence = ["No strong segment cues detected in sampled public text."]

    return {
        "segment": segment,
        "confidence": confidence,
        "evidence": evidence,
        "implications": implications,
    }

def classify_visibility_vs_capability(by_layer: Dict[str, List[Dict[str, Any]]], segment_inference: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turns 'Unknown' into an MD-useful stance:
    - Visibility gap: likely exists internally but isn't publicly observable
    - Potential capability gap: uncertain (not universally present)
    """
    seg = (segment_inference or {}).get("segment", "").lower()

    def likely_exists(layer_name: str) -> bool:
        # Core systems almost certainly exist, especially for luxury/destination properties.
        if "luxury" in seg:
            return layer_name in {"Distribution", "Core Systems", "Operations", "Finance & Reporting"}
        return layer_name in {"Distribution", "Core Systems", "Finance & Reporting"}

    out: List[Dict[str, Any]] = []
    for layer in CANONICAL_LAYER_ORDER:
        dets = by_layer.get(layer, []) or []
        visible = len(dets) > 0

        if visible:
            gap_type = "No visibility gap"
            rationale = "Public signals indicate systems are observable."
        else:
            if likely_exists(layer):
                gap_type = "Visibility gap (likely present but not observable)"
                rationale = "Hotels of this type almost always operate these systems; lack of web signals suggests hidden integrations or vendor opacity."
            else:
                gap_type = "Potential capability gap (uncertain)"
                rationale = "Insufficient public evidence and not universally present in comparable hotels; treat as an investigation priority."

        out.append({"layer": layer, "gap_type": gap_type, "rationale": rationale})
    return {"gap_summary": out}

def build_exec_priorities(segment_inference: Dict[str, Any], by_layer: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Opinionated 'Top 3' executive priorities based on segment + tracking foundation.
    """
    segment = (segment_inference or {}).get("segment", "").lower()
    commercial_tools = by_layer.get("Commercial Execution", []) or []
    has_gtm = any(
        ("google tag manager" in (d.get("product", "") or "").lower())
        or ("google tag manager" in (d.get("vendor", "") or "").lower())
        for d in commercial_tools
        if isinstance(d, dict) and d.get("label") == "confirmed"
    )

    priorities: List[Dict[str, Any]] = []

    priorities.append({
        "title": "Map the end-to-end data flow (booking → guest identity → marketing → reporting) and fix integration breakpoints",
        "why_now": "Integration health is the main constraint on automation, attribution accuracy, and CRM personalisation.",
        "what_good_looks_like": [
            "Single guest identity across booking engine, PMS, and ancillary systems (spa/events) where applicable",
            "Clean booking conversion events into GA4 and reliable channel attribution for direct bookings",
            "Weekly commercial dashboard fed from source systems (not spreadsheets)",
        ],
        "exec_questions": [
            "Where does guest identity fragment today (rooms vs spa vs events)?",
            "Which integrations are brittle/manual, and what fails silently?",
            "Which KPIs are we trusting that are actually modelled or estimated?",
        ],
    })

    if has_gtm:
        priorities.append({
            "title": "Turn GTM into full-funnel measurement (GA4 + booking engine events + metasearch hygiene)",
            "why_now": "You have a tracking foundation (GTM) but without clean GA4 and conversion plumbing you cannot steer spend confidently.",
            "what_good_looks_like": [
                "GA4 configured with consistent event schema across site + booking engine",
                "Paid channels receiving correct conversion signals (value and room nights where possible)",
                "Attribution model documented and governed (stable tag changes)",
            ],
            "exec_questions": [
                "Can we reconcile marketing reporting to actual bookings without debate?",
                "Do we track abandon/step completion in the booking journey?",
                "Is metasearch measured on incrementality or last-click?",
            ],
        })
    else:
        priorities.append({
            "title": "Establish a measurement backbone (GTM + GA4 + conversion plumbing)",
            "why_now": "Without measurement hygiene, commercial improvements are hard to prove, sustain, or scale.",
            "what_good_looks_like": [
                "GTM deployed with governance and change control",
                "GA4 capturing booking-engine events reliably",
                "Marketing ROI available by channel with confidence",
            ],
            "exec_questions": [
                "What percentage of bookings are unattributed/unknown today?",
                "Which channel metrics do we not trust (and why)?",
            ],
        })

    if "luxury" in segment:
        priorities.append({
            "title": "Reduce manual revenue decisions: pricing guardrails + demand signals + forecast discipline",
            "why_now": "Luxury/destination hotels often leak revenue through slow reaction time and inconsistent human override.",
            "what_good_looks_like": [
                "Clear pricing rules + exceptions policy and sign-off thresholds",
                "Forecast cadence tied to events/pace and demand signals",
                "Documented strategy by segment (weekday corporate vs weekend/leisure peaks)",
            ],
            "exec_questions": [
                "Where are we overriding recommendations most often, and are we right?",
                "Do we have a single view of pace, pickup, and displacement across segments?",
            ],
        })
    else:
        priorities.append({
            "title": "Tighten direct mix economics: channel roles + parity + booking journey conversion tests",
            "why_now": "Direct mix is often the fastest path to profit; the work is operationally simple but requires discipline.",
            "what_good_looks_like": [
                "Defined channel roles (OTA vs metasearch vs brand search)",
                "Parity monitored and enforced",
                "Booking journey conversion improved via measurable tests",
            ],
            "exec_questions": [
                "What is our true net cost of acquisition by channel?",
                "Where do we lose customers in the booking flow?",
            ],
        })

    return {"exec_priorities_top3": priorities[:3]}


# ----------------------------
# Layer summary builder
# ----------------------------
def build_layer_summary(by_layer: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Converts detections-by-layer into an MD-friendly layer summary:
    - visibility: Detected / Not publicly visible
    - detections: list
    - likely_state + typical_risk when not visible
    - strategic_importance + rationale always
    """
    summary: Dict[str, Any] = {}
    for layer in CANONICAL_LAYER_ORDER:
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
    Baseline peer benchmark segment used for score interpretation.
    Keep simple and stable; segment inference is also provided separately for narrative quality.
    """
    return "lifestyle_boutique"


def fallback_response(error: Dict[str, Any], model_inputs: Dict[str, Any], url: Optional[str] = None) -> Dict[str, Any]:
    """
    Always returns valid JSON. Never raises.
    """
    try:
        opp = opportunity_model(model_inputs)
    except Exception as e:
        opp = {
            "assumptions": {"rooms": 60, "occupancy": 0.72, "adr": 140},
            "annual_opportunity_gbp_range": [0, 0],
            "error": f"opportunity_model failed: {str(e)}",
        }

    segment = choose_segment(url or "")
    benchmark = PEER_BENCHMARKS.get(segment, PEER_BENCHMARKS["lifestyle_boutique"])

    empty_by_layer = {layer: [] for layer in CANONICAL_LAYER_ORDER}
    analysis = {
        "url": url,
        "detections": [],
        "scores": {"overall_score_0_to_100": None, "layer_scores": []},
        "benchmarks": {
            "segment": segment,
            "typical_range": list(benchmark["typical_range"]),
            "best_in_class": benchmark["best_in_class"],
            "interpretation": "Score unavailable due to limited public signals.",
        },
        "layers": build_layer_summary(empty_by_layer),
        "roadmap": ROADMAP,
        "opportunity": opp,
        "error": error,
        "notes": [
            "Public technology signals could not be processed for this website at this time.",
            "This may be due to bot protection, heavy JavaScript, rate limits, or an internal processing edge case.",
            "Confirming one internal system (PMS / booking engine / channel manager / CRM) will improve accuracy.",
        ],
    }

    report_md = (
        "# Hotel Technology & Revenue Readiness Report\n\n"
        "We couldn’t complete the automated scan just now.\n\n"
        "This does **not** indicate a problem with your systems — it’s often caused by sites restricting automated access "
        "or by a processing edge case.\n\n"
        "If you confirm your PMS, booking engine, channel manager or CRM/email platform, I’ll regenerate a full consultant-grade report.\n"
    )

    return {"analysis": analysis, "report_md": report_md}


# ----------------------------
# Healthcheck
# ----------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


# ----------------------------
# Main endpoint
# ----------------------------
@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """
    Hard guarantee: never throws, never returns 500.
    Always returns HTTP 200 with an analysis object (and a best-effort report).
    """
    url = normalise_url(req.url)

    model_inputs = {"rooms": req.rooms, "occupancy": req.occupancy, "adr": req.adr}

    try:
        # 1) Fetch HTML (safe)
        html, fetch_error = await fetch_html(url)
        if fetch_error:
            return fallback_response(fetch_error, model_inputs, url=url)

        # 2) Parse HTML (safe)
        soup = BeautifulSoup(html, "lxml")
        public_text = soup.get_text(" ", strip=True)

        # Collect asset references (absolute and raw), plus domains
        assets: set[str] = set()
        asset_domains: set[str] = set()

        def _add_asset(val: str):
            if not val:
                return
            v = val.strip()
            if not v:
                return
            assets.add(v)
            try:
                abs_v = urljoin(url, v)
                assets.add(abs_v)
                host = (urlparse(abs_v).netloc or "").lower()
                if host:
                    asset_domains.add(host)
            except Exception:
                pass

        for tag in soup.find_all(["script", "iframe", "img", "a", "link", "form"]):
            _add_asset(tag.get("src") or "")
            _add_asset(tag.get("href") or "")
            _add_asset(tag.get("action") or "")

        # 3) Detect tools (safe)
        detectors = load_detectors()

        detections: List[Dict[str, Any]] = []
        by_layer: Dict[str, List[Dict[str, Any]]] = {layer: [] for layer in CANONICAL_LAYER_ORDER}

        # Include additional searchable strings to improve detection without JS execution
        searchable_blob = " ".join([html, public_text, " ".join(sorted(assets)), " ".join(sorted(asset_domains))])

        for product in detectors:
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

                    v = str(value)

                    if ptype == "domain_contains":
                        # matches in asset URLs or domains
                        if any(v in a for a in assets) or any(v in d for d in asset_domains):
                            best = max(best, weight)

                    elif ptype == "text_regex":
                        # search across combined blob (html + visible text + assets)
                        if safe_regex(v, searchable_blob):
                            best = max(best, weight)

                    elif ptype == "text_contains":
                        if v.lower() in searchable_blob.lower():
                            best = max(best, weight)

            if best > 0:
                det = {
                    "vendor": vendor,
                    "product": prod,
                    "category": category,
                    "confidence": round(best, 2),
                    "label": label(best),
                }
                detections.append(det)

                layer = map_category_to_layer(category)
                if layer not in by_layer:
                    # Keep it safe: unknown categories go to Commercial Execution
                    layer = "Commercial Execution"
                by_layer[layer].append(det)

        # 4) Score + opportunity (safe)
        try:
            scores = score_layers(by_layer)
        except Exception as e:
            logger.error("ERROR in score_layers:\n%s", traceback.format_exc())
            scores = {
                "overall_score_0_to_100": None,
                "layer_scores": [],
                "error": f"score_layers failed: {str(e)}",
            }

        try:
            opp = opportunity_model(model_inputs)
        except Exception as e:
            logger.error("ERROR in opportunity_model:\n%s", traceback.format_exc())
            opp = {
                "assumptions": {"rooms": 60, "occupancy": 0.72, "adr": 140},
                "annual_opportunity_gbp_range": [0, 0],
                "error": f"opportunity_model failed: {str(e)}",
            }

        # 5) Benchmarks + interpretation (peer segment for scoring context)
        peer_segment = choose_segment(url)
        benchmark = PEER_BENCHMARKS.get(peer_segment, PEER_BENCHMARKS["lifestyle_boutique"])
        score_text = interpret_score(scores.get("overall_score_0_to_100"), benchmark)

        # 6) Layer summaries (likely-state + strategic importance)
        layers = build_layer_summary(by_layer)

        # 7) MD-grade enhancers
        segment_inference = infer_hotel_segment(public_text=public_text, url=url)
        gaps = classify_visibility_vs_capability(by_layer=by_layer, segment_inference=segment_inference)
        exec_priorities = build_exec_priorities(segment_inference=segment_inference, by_layer=by_layer)

        analysis: Dict[str, Any] = {
            "url": url,
            "detections": detections,
            "scores": scores,
            "benchmarks": {
                "segment": peer_segment,
                "typical_range": list(benchmark["typical_range"]),
                "best_in_class": benchmark["best_in_class"],
                "interpretation": score_text,
            },
            "segment_inference": segment_inference,
            "gaps": gaps,
            "exec_priorities_top3": exec_priorities.get("exec_priorities_top3", []),
            "layers": layers,
            "roadmap": ROADMAP,
            "opportunity": opp,
            "notes": [
                "Some hotel systems are not publicly visible and may require confirmation.",
                "Confidence labels reflect public signal strength only (not internal usage quality).",
                "This assessment is vendor-neutral and uses public web signals + benchmarks.",
            ],
        }

        # 8) Render report (safe)
        try:
            report_md = render_report_md(analysis)
        except TypeError:
            # Backwards compatible: old renderer expects only scores/opportunity
            report_md = render_report_md({"scores": scores, "opportunity": opp})
        except Exception as e:
            logger.error("ERROR in render_report_md:\n%s", traceback.format_exc())
            report_md = (
                "# Hotel Technology & Revenue Readiness Report\n\n"
                "Analysis completed, but report generation hit a formatting issue.\n\n"
                f"**Error:** {str(e)}\n"
            )

        return {"analysis": analysis, "report_md": report_md}

    except Exception as e:
        logger.error("UNHANDLED ERROR in /analyze:\n%s", traceback.format_exc())
        return fallback_response(
            {"type": "unhandled_processing_error", "message": str(e)},
            model_inputs,
            url=url,
        )
