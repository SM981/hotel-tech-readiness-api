import re
import json
import traceback
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

import yaml
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI
from pydantic import BaseModel, Field

from scoring import score_layers
from report import render_report_md, opportunity_model

# ----------------------------
# Logging
# ----------------------------
logger = logging.getLogger("hotel_tech_readiness")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Hotel Tech Readiness API", version="0.5.1")

# ----------------------------
# In-file defaults (NO external module dependency)
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

# Minimal strategic importance (kept simple; tune later)
STRATEGIC_IMPORTANCE: Dict[str, Tuple[str, str]] = {
    "Distribution": ("High", "Controls visibility, cost of acquisition, and rate integrity across channels."),
    "Core Systems": ("High", "PMS/RMS integration underpins operational efficiency and pricing discipline."),
    "Guest Data & CRM": ("High", "Enables repeat/direct growth, segmentation, consent and lifecycle automation."),
    "Commercial Execution": ("High", "Tracking/attribution determines whether you can invest with confidence."),
    "In-Venue Experience": ("Medium", "Guest experience tech can lift NPS, upsell and service efficiency."),
    "Operations": ("Medium", "Task/housekeeping/maintenance tooling reduces labour and improves consistency."),
    "Finance & Reporting": ("Medium", "A single KPI view reduces decision lag and manual consolidation."),
}

# Conservative likely-state + risk when not visible publicly
LIKELY_STATE_BY_LAYER: Dict[str, Dict[str, str]] = {
    "Distribution": {
        "likely_state": "A booking engine/CRS and channel management capability likely exists (often group-managed).",
        "typical_risk": "If parity/restrictions are not governed centrally, OTA dependence and rate leakage increase.",
    },
    "Core Systems": {
        "likely_state": "A PMS exists; RMS may be present but is typically not visible via public web signals.",
        "typical_risk": "Without reliable PMS↔RMS plumbing, pricing becomes slower and more manual.",
    },
    "Guest Data & CRM": {
        "likely_state": "Some form of guest communications and database exists; CRM depth varies.",
        "typical_risk": "Fragmented identities limit personalisation, repeat growth, and measurable lifecycle uplift.",
    },
    "Commercial Execution": {
        "likely_state": "Analytics tags are often present; depth depends on booking funnel instrumentation.",
        "typical_risk": "Weak conversion plumbing leads to unreliable ROI decisions and wasted spend.",
    },
    "In-Venue Experience": {
        "likely_state": "In-stay tech may exist but usually isn’t visible from a single public URL.",
        "typical_risk": "Missed upsell moments and inconsistent service handoffs.",
    },
    "Operations": {
        "likely_state": "Ops tooling exists in most hotels but is rarely publicly detectable.",
        "typical_risk": "Manual coordination drives labour waste and slower response times.",
    },
    "Finance & Reporting": {
        "likely_state": "Finance/reporting stack exists but is not publicly visible.",
        "typical_risk": "Decisions rely on lagging spreadsheets and inconsistent KPI definitions.",
    },
}

# Simple roadmap (safe default)
ROADMAP = {
    "Now (0–30 days)": {
        "outcome": "Confirm core systems + instrumentation and remove the biggest blind spots.",
        "exec_question": "What do we *not* know today that prevents confident commercial decisions?",
    },
    "Next (31–60 days)": {
        "outcome": "Fix booking funnel tracking + data flow mapping across systems.",
        "exec_question": "Where does guest identity, attribution or reporting break today?",
    },
    "Later (61–90 days)": {
        "outcome": "Deploy a single KPI layer and pilot one automation with measurable impact.",
        "exec_question": "Which one automation would move profit fastest without replatforming?",
    },
}

# Peer benchmarks (optional; keep lightweight)
PEER_BENCHMARKS = {
    "lifestyle_boutique": {"typical_range": (40, 62), "best_in_class": 78}
}

# ----------------------------
# OpenAPI Models
# ----------------------------
class AnalyzeRequest(BaseModel):
    url: str
    competitor_url: str | None = None

    rooms: int | None = None
    occupancy: float | None = None
    adr: float | None = None

    pms_vendor: str | None = None
    booking_engine_vendor: str | None = None
    channel_manager_vendor: str | None = None
    crm_vendor: str | None = None


class AnalyzeResponse(BaseModel):
    analysis: Dict[str, Any] = Field(..., description="Full structured analysis object.")
    report_md: str = Field(..., description="C-suite report in Markdown.")


# ----------------------------
# Mapping (detectors.yaml category -> canonical layer)
# ----------------------------
CATEGORY_TO_LAYER = {
    "distribution": "Distribution",
    "crs": "Distribution",
    "channel_manager": "Distribution",
    "channel manager": "Distribution",
    "ota": "Distribution",
    "metasearch": "Distribution",
    "booking engine": "Distribution",
    "booking_engine": "Distribution",

    "pms": "Core Systems",
    "rms": "Core Systems",
    "property management": "Core Systems",
    "revenue management": "Core Systems",

    "crm": "Guest Data & CRM",
    "email": "Guest Data & CRM",
    "marketing automation": "Guest Data & CRM",
    "loyalty": "Guest Data & CRM",

    "tracking": "Commercial Execution",
    "analytics": "Commercial Execution",
    "attribution": "Commercial Execution",
    "tag manager": "Commercial Execution",
    "advertising": "Commercial Execution",

    "in-venue": "In-Venue Experience",
    "guest messaging": "In-Venue Experience",
    "digital check-in": "In-Venue Experience",
    "upsell": "In-Venue Experience",

    "operations": "Operations",
    "housekeeping": "Operations",
    "maintenance": "Operations",
    "task management": "Operations",

    "finance": "Finance & Reporting",
    "accounting": "Finance & Reporting",
    "bi": "Finance & Reporting",
    "reporting": "Finance & Reporting",
    "dashboard": "Finance & Reporting",
}


def map_category_to_layer(category: str) -> str:
    c = (category or "").strip().lower()
    if not c:
        return "Commercial Execution"
    if category in CANONICAL_LAYER_ORDER:
        return category
    return CATEGORY_TO_LAYER.get(c, "Commercial Execution")


# ----------------------------
# HTTP safety + crawl policy
# ----------------------------
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

CRAWL_TIMEOUT = 25
MAX_PAGES = 14
MAX_INTERNAL_LINKS = 12
MAX_TEXT_CHARS = 600_000
MAX_COOKIE_KEYS = 80


def normalise_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme:
        return f"https://{url}"
    return url


def safe_regex(pattern: str, haystack: str) -> bool:
    try:
        return re.search(pattern, haystack, re.I) is not None
    except re.error:
        return False


def label(conf: float) -> str:
    if conf >= 0.85:
        return "confirmed"
    if conf >= 0.55:
        return "probable"
    if conf > 0:
        return "possible"
    return "unknown"


@lru_cache(maxsize=1)
def load_detectors() -> List[Dict[str, Any]]:
    try:
        with open("detectors.yaml", "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        products = data.get("products", [])
        if not isinstance(products, list):
            return []
        return [p for p in products if isinstance(p, dict)]
    except Exception:
        logger.error("ERROR loading detectors.yaml:\n%s", traceback.format_exc())
        return []


# ----------------------------
# Customer-confirmed injection
# ----------------------------
def inject_confirmed_system(
    by_layer: Dict[str, List[Dict[str, Any]]],
    detections: List[Dict[str, Any]],
    vendor: Optional[str],
    layer: str,
    category: str,
    product: str,
):
    if not vendor:
        return
    det = {
        "vendor": vendor,
        "product": product,
        "category": category,
        "confidence": 0.99,
        "label": "confirmed",
        "source": "customer_confirmed",
    }
    by_layer.setdefault(layer, []).append(det)
    detections.append(det)


# ----------------------------
# Crawl + signal aggregation
# ----------------------------
@dataclass
class PageResult:
    url: str
    status_code: int
    content_type: str
    html: str
    headers: Dict[str, str]
    cookies: Dict[str, str]


def _truncate(s: str, limit: int) -> str:
    return (s or "")[:limit]


def _internal_links(base_url: str, soup: BeautifulSoup, limit: int) -> List[str]:
    out: List[str] = []
    base_host = (urlparse(base_url).netloc or "").lower()

    def _good(h: str) -> bool:
        if not h:
            return False
        h = h.strip()
        if not h or h.startswith("#"):
            return False
        if h.lower().startswith(("mailto:", "tel:", "javascript:")):
            return False
        return True

    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not _good(href):
            continue
        abs_u = urljoin(base_url, href)
        host = (urlparse(abs_u).netloc or "").lower()
        if host != base_host:
            continue
        if abs_u not in out:
            out.append(abs_u)
        if len(out) >= limit:
            break
    return out


_BOOKING_KEYWORDS = ["book", "booking", "reserve", "reservation", "availability", "rooms", "rates", "offers"]


def _booking_candidates(base_url: str, soup: BeautifulSoup) -> List[str]:
    cands: List[str] = []

    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        text = (a.get_text(" ", strip=True) or "").lower()
        href_l = href.lower()
        if any(k in text for k in _BOOKING_KEYWORDS) or any(k in href_l for k in _BOOKING_KEYWORDS):
            cands.append(urljoin(base_url, href))

    for f in soup.find_all("form"):
        action = (f.get("action") or "").strip()
        if action and any(k in action.lower() for k in _BOOKING_KEYWORDS):
            cands.append(urljoin(base_url, action))

    for i in soup.find_all("iframe"):
        src = (i.get("src") or "").strip()
        if src and any(k in src.lower() for k in _BOOKING_KEYWORDS):
            cands.append(urljoin(base_url, src))

    # stable dedupe
    seen = set()
    out = []
    for u in cands:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:6]


async def _safe_get(client: httpx.AsyncClient, url: str) -> Tuple[Optional[PageResult], Optional[Dict[str, Any]]]:
    try:
        r = await client.get(url)
        ct = (r.headers.get("content-type") or "").lower()

        html = ""
        if any(x in ct for x in ["text/html", "application/xhtml+xml", "text/plain", "application/xml", "text/xml"]):
            html = r.text or ""

        headers = {}
        for hk, hv in r.headers.items():
            if hk.lower() in {"server", "x-powered-by", "via", "x-cache", "cf-ray", "x-amz-cf-id"}:
                headers[hk] = str(hv)

        cookies = {}
        for k, v in r.cookies.items():
            if len(cookies) >= MAX_COOKIE_KEYS:
                break
            cookies[str(k)] = str(v)

        return PageResult(
            url=str(r.url),
            status_code=int(r.status_code),
            content_type=ct,
            html=html,
            headers=headers,
            cookies=cookies,
        ), None
    except httpx.TimeoutException:
        return None, {"type": "timeout", "message": "Upstream request timed out", "url": url}
    except httpx.RequestError as e:
        return None, {"type": "request_error", "message": str(e), "url": url}
    except Exception as e:
        return None, {"type": "unexpected_error", "message": str(e), "url": url}


async def crawl_site_signals(root_url: str) -> Dict[str, Any]:
    root_url = normalise_url(root_url)
    parsed = urlparse(root_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    pages: List[PageResult] = []
    errors: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(
        headers=BROWSER_HEADERS,
        follow_redirects=True,
        timeout=CRAWL_TIMEOUT,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    ) as client:
        home, err = await _safe_get(client, root_url)
        if err or not home:
            return {"root_url": root_url, "base": base, "pages": [], "errors": [err or {"type": "no_home"}]}

        pages.append(home)

        # basic extras
        for p in [urljoin(base, "/robots.txt"), urljoin(base, "/sitemap.xml")]:
            if len(pages) >= MAX_PAGES:
                break
            pr, pe = await _safe_get(client, p)
            if pe:
                errors.append(pe)
            elif pr:
                pages.append(pr)

        # internal links
        try:
            soup = BeautifulSoup(home.html or "", "lxml")
            internal = _internal_links(root_url, soup, MAX_INTERNAL_LINKS)
        except Exception:
            internal = []

        for u in internal:
            if len(pages) >= MAX_PAGES:
                break
            pr, pe = await _safe_get(client, u)
            if pe:
                errors.append(pe)
            elif pr:
                pages.append(pr)

        # booking flow
        booking_flow = {"candidates": [], "final_url": None, "final_domain": None, "evidence": []}
        try:
            soup_home = BeautifulSoup(home.html or "", "lxml")
            cands = _booking_candidates(root_url, soup_home)
            booking_flow["candidates"] = cands

            if cands:
                cand = cands[0]
                try:
                    rr = await client.get(cand, follow_redirects=True)
                    booking_flow["final_url"] = str(rr.url)
                    booking_flow["final_domain"] = (urlparse(str(rr.url)).netloc or "").lower()
                    chain = [str(h.url) for h in getattr(rr, "history", [])][:6]
                    if chain:
                        booking_flow["evidence"].append({"type": "redirect_chain", "value": chain})
                    booking_flow["evidence"].append({"type": "booking_candidate", "value": cand})
                    booking_flow["evidence"].append({"type": "booking_final_url", "value": booking_flow["final_url"]})
                    booking_flow["evidence"].append({"type": "booking_cookie_keys", "value": list(rr.cookies.keys())[:30]})
                except Exception:
                    booking_flow["evidence"].append({"type": "booking_flow_error", "value": "Could not follow booking candidate."})
        except Exception:
            booking_flow["evidence"].append({"type": "booking_flow_error", "value": "Booking discovery failed."})

    # aggregate
    asset_domains: List[str] = []
    asset_urls: List[str] = []
    headers_union: Dict[str, str] = {}
    cookie_keys_union: List[str] = []
    combined_parts: List[str] = []
    jsonld_union: List[Dict[str, Any]] = []

    for pr in pages:
        headers_union.update(pr.headers or {})
        for ck in (pr.cookies or {}).keys():
            if ck not in cookie_keys_union:
                cookie_keys_union.append(ck)
                if len(cookie_keys_union) >= MAX_COOKIE_KEYS:
                    break

        html = pr.html or ""
        if not html:
            continue

        combined_parts.append(html)
        try:
            soup = BeautifulSoup(html, "lxml")
            combined_parts.append(soup.get_text(" ", strip=True))

            # assets
            for tag in soup.find_all(["script", "iframe", "img", "a", "link", "form"]):
                for attr in ["src", "href", "action"]:
                    val = (tag.get(attr) or "").strip()
                    if not val:
                        continue
                    abs_u = urljoin(pr.url, val)
                    asset_urls.append(abs_u)
                    host = (urlparse(abs_u).netloc or "").lower()
                    if host:
                        asset_domains.append(host)

            # json-ld
            for tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
                raw = (tag.string or "").strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        jsonld_union.append(data)
                    elif isinstance(data, list):
                        jsonld_union.extend([x for x in data if isinstance(x, dict)])
                except Exception:
                    pass
        except Exception:
            pass

    asset_domains = sorted(list({d for d in asset_domains if d}))
    asset_urls = list(dict.fromkeys(asset_urls))

    blob = _truncate(" ".join(combined_parts), MAX_TEXT_CHARS)

    evidence = {
        "pages_fetched": [{"url": p.url, "status": p.status_code, "content_type": p.content_type} for p in pages],
        "headers_observed": headers_union,
        "cookie_keys_observed": cookie_keys_union,
        "top_third_party_domains": asset_domains[:40],
        "booking_flow": booking_flow,
        "structured_data_snippets": _truncate(str(jsonld_union[:3]), 8000),
        "crawl_errors": errors[:8],
    }

    return {
        "root_url": root_url,
        "base": base,
        "pages": pages,
        "asset_urls": asset_urls,
        "asset_domains": asset_domains,
        "headers": headers_union,
        "cookie_keys": cookie_keys_union,
        "booking_flow": booking_flow,
        "jsonld": jsonld_union,
        "blob": blob,
        "evidence": evidence,
        "errors": errors,
    }


# ----------------------------
# Detection
# ----------------------------
def detect_tools_from_signals(signals: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    detectors = load_detectors()

    blob = signals.get("blob") or ""
    asset_domains = set(signals.get("asset_domains") or [])
    asset_urls = set(signals.get("asset_urls") or [])
    cookie_keys = set(signals.get("cookie_keys") or [])
    headers = signals.get("headers") or {}
    booking_final = ((signals.get("booking_flow") or {}).get("final_domain") or "").lower()
    booking_candidates = (signals.get("booking_flow") or {}).get("candidates") or []

    searchable_parts = [
        blob,
        " ".join(sorted(asset_domains)),
        " ".join(sorted(asset_urls)),
        " ".join(sorted(cookie_keys)),
        " ".join([f"{k}:{v}" for k, v in headers.items()]),
        booking_final,
        " ".join(booking_candidates),
    ]
    searchable_blob = _truncate(" ".join([p for p in searchable_parts if p]), MAX_TEXT_CHARS)

    detections: List[Dict[str, Any]] = []
    by_layer: Dict[str, List[Dict[str, Any]]] = {layer: [] for layer in CANONICAL_LAYER_ORDER}

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
                    if any(v in d for d in asset_domains) or (booking_final and v in booking_final):
                        best = max(best, weight)

                elif ptype == "text_regex":
                    if safe_regex(v, searchable_blob):
                        best = max(best, weight)

                elif ptype == "text_contains":
                    if v.lower() in searchable_blob.lower():
                        best = max(best, weight)

                elif ptype == "cookie_contains":
                    if any(v.lower() in ck.lower() for ck in cookie_keys):
                        best = max(best, weight)

        if best > 0:
            det = {
                "vendor": vendor,
                "product": prod,
                "category": category,
                "confidence": round(best, 2),
                "label": label(best),
                "source": "public_signal",
            }
            detections.append(det)
            layer = map_category_to_layer(category)
            by_layer.setdefault(layer, []).append(det)

    return detections, by_layer


# ----------------------------
# Layers (Observed/Inferred)
# ----------------------------
def build_layer_summary(by_layer: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for layer in CANONICAL_LAYER_ORDER:
        dets = by_layer.get(layer, []) or []
        importance, rationale = STRATEGIC_IMPORTANCE.get(layer, ("Medium", ""))

        fallback = LIKELY_STATE_BY_LAYER.get(layer, {})
        if dets:
            summary[layer] = {
                "visibility": "Observed",
                "visibility_state": "Observed",
                "strategic_importance": importance,
                "importance_rationale": rationale,
                "detections": dets,
                "likely_state": fallback.get("likely_state"),
                "typical_risk": fallback.get("typical_risk"),
            }
        else:
            summary[layer] = {
                "visibility": "Inferred",
                "visibility_state": "Inferred",
                "strategic_importance": importance,
                "importance_rationale": rationale,
                "detections": [],
                "likely_state": fallback.get("likely_state"),
                "typical_risk": fallback.get("typical_risk"),
            }
    return summary


# ----------------------------
# Benchmarks
# ----------------------------
def choose_peer_segment(url: str) -> str:
    return "lifestyle_boutique"


def interpret_score(overall_score: Optional[float], benchmark: Dict[str, Any]) -> str:
    if overall_score is None:
        return "Score unavailable from public signals."
    lo, hi = benchmark.get("typical_range", (40, 62))
    best = benchmark.get("best_in_class", 78)
    if overall_score < lo:
        return "Below typical peer range: fundamentals and integration visibility likely constrain performance."
    if overall_score <= hi:
        return "Within typical peer range: solid foundations, with clear opportunities to harden measurement and automation."
    if overall_score < best:
        return "Above typical peer range: maturity is strong; focus on marginal gains and governance."
    return "Best-in-class: strong visibility and commercial plumbing; maintain change control and discipline."


# ----------------------------
# Comparison
# ----------------------------
def compute_comparison(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    try:
        a_score = (a.get("scores") or {}).get("overall_score_0_to_100")
        b_score = (b.get("scores") or {}).get("overall_score_0_to_100")
        delta = None
        if isinstance(a_score, (int, float)) and isinstance(b_score, (int, float)):
            delta = round(a_score - b_score, 1)

        a_book = (((a.get("evidence") or {}).get("booking_flow") or {}).get("final_domain"))
        b_book = (((b.get("evidence") or {}).get("booking_flow") or {}).get("final_domain"))

        return {
            "score_delta": delta,
            "booking_engine_domain_a": a_book,
            "booking_engine_domain_b": b_book,
            "notes": [
                "Comparison uses identical public-signal scan logic for both hotels.",
                "Differences reflect public visibility + booking journey plumbing, not internal quality.",
            ],
        }
    except Exception:
        return {"error": "comparison_failed", "notes": ["Comparison could not be computed safely."]}


# ----------------------------
# Healthcheck
# ----------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


# ----------------------------
# Fallback
# ----------------------------
def fallback_response(error: Dict[str, Any], model_inputs: Dict[str, Any], url: Optional[str] = None) -> Dict[str, Any]:
    try:
        opp = opportunity_model(model_inputs)
    except Exception as e:
        opp = {"assumptions": {"rooms": 60, "occupancy": 0.72, "adr": 140}, "annual_opportunity_gbp_range": [0, 0], "error": str(e)}

    benchmark = PEER_BENCHMARKS["lifestyle_boutique"]
    analysis = {
        "url": url,
        "detections": [],
        "scores": {"overall_score_0_to_100": None, "layer_scores": []},
        "benchmarks": {"segment": "lifestyle_boutique", "typical_range": list(benchmark["typical_range"]), "best_in_class": benchmark["best_in_class"], "interpretation": "Score unavailable due to limited public signals."},
        "layers": build_layer_summary({layer: [] for layer in CANONICAL_LAYER_ORDER}),
        "roadmap": ROADMAP,
        "opportunity": opp,
        "evidence": {"crawl_errors": [error]},
        "error": error,
    }
    return {"analysis": analysis, "report_md": render_report_md(analysis)}


# ----------------------------
# Main endpoint
# ----------------------------
@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    url = normalise_url(req.url)
    competitor_url = normalise_url(req.competitor_url) if req.competitor_url else None
    model_inputs = {"rooms": req.rooms, "occupancy": req.occupancy, "adr": req.adr}

    try:
        signals = await crawl_site_signals(url)
        if not signals.get("pages"):
            return fallback_response({"type": "crawl_failed", "message": "No pages fetched."}, model_inputs, url=url)

        detections, by_layer = detect_tools_from_signals(signals)

        inject_confirmed_system(by_layer, detections, req.pms_vendor, "Core Systems", "PMS", "Property Management System")
        inject_confirmed_system(by_layer, detections, req.booking_engine_vendor, "Distribution", "Booking Engine", "Booking Engine")
        inject_confirmed_system(by_layer, detections, req.channel_manager_vendor, "Distribution", "Channel Manager", "Channel Manager")
        inject_confirmed_system(by_layer, detections, req.crm_vendor, "Guest Data & CRM", "CRM", "CRM / Guest Data Platform")

        try:
            scores = score_layers(by_layer)
        except Exception as e:
            logger.error("ERROR in score_layers:\n%s", traceback.format_exc())
            scores = {"overall_score_0_to_100": None, "layer_scores": [], "error": str(e)}

        try:
            opp = opportunity_model(model_inputs)
        except Exception as e:
            logger.error("ERROR in opportunity_model:\n%s", traceback.format_exc())
            opp = {"assumptions": {"rooms": 60, "occupancy": 0.72, "adr": 140}, "annual_opportunity_gbp_range": [0, 0], "error": str(e)}

        peer_segment = choose_peer_segment(url)
        benchmark = PEER_BENCHMARKS.get(peer_segment, PEER_BENCHMARKS["lifestyle_boutique"])
        score_text = interpret_score(scores.get("overall_score_0_to_100"), benchmark)

        layers = build_layer_summary(by_layer)

        analysis: Dict[str, Any] = {
            "url": url,
            "detections": detections,
            "scores": scores,
            "benchmarks": {"segment": peer_segment, "typical_range": list(benchmark["typical_range"]), "best_in_class": benchmark["best_in_class"], "interpretation": score_text},
            "layers": layers,
            "roadmap": ROADMAP,
            "opportunity": opp,
            "evidence": signals.get("evidence") or {},
            "notes": [
                "Bounded crawl: homepage + internal pages + booking flow (where discoverable).",
                "Visibility states are Observed/Inferred; lack of observation does not imply absence.",
                "Vendor-neutral by design; examples are illustrative, not recommendations.",
            ],
        }

        if competitor_url:
            try:
                comp_signals = await crawl_site_signals(competitor_url)
                comp_dets, comp_by_layer = detect_tools_from_signals(comp_signals)
                try:
                    comp_scores = score_layers(comp_by_layer)
                except Exception:
                    comp_scores = {"overall_score_0_to_100": None, "layer_scores": [], "error": "score_layers_failed"}
                comp_layers = build_layer_summary(comp_by_layer)
                competitor_analysis = {
                    "url": competitor_url,
                    "detections": comp_dets,
                    "scores": comp_scores,
                    "layers": comp_layers,
                    "evidence": comp_signals.get("evidence") or {},
                }
                analysis["competitor"] = competitor_analysis
                analysis["comparison"] = compute_comparison(analysis, competitor_analysis)
            except Exception:
                logger.error("Competitor scan failed:\n%s", traceback.format_exc())
                analysis["comparison"] = {"error": "competitor_scan_failed"}

        report_md = render_report_md(analysis)
        return {"analysis": analysis, "report_md": report_md}

    except Exception as e:
        logger.error("UNHANDLED ERROR:\n%s", traceback.format_exc())
        return fallback_response({"type": "unhandled_processing_error", "message": str(e)}, model_inputs, url=url)
