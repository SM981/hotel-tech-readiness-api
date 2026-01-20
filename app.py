import re
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

# -------------------------------------------------------------------
# HARDENED IMPORTS (never let a report.py change brick the service)
# -------------------------------------------------------------------
try:
    from report import opportunity_model, render_report_md
except Exception:
    def opportunity_model(_inputs):
        return {
            "assumptions": {"rooms": 60, "occupancy": 0.72, "adr": 140},
            "annual_opportunity_gbp_range": [0, 0],
            "scope_note": "Opportunity model unavailable due to report import error.",
        }

    def render_report_md(_payload):
        return (
            "# Hotel Technology & Revenue Readiness Assessment\n\n"
            "Report generation unavailable due to a server-side import error.\n"
        )

# Benchmarks + interpretation + likely-state + weighting + roadmap
from benchmarks import PEER_BENCHMARKS
from interpretation import interpret_score

# NOTE: these modules must exist in your repo; if you renamed them, update imports accordingly.
from inference import LIKELY_STATE_BY_LAYER
from weighting import STRATEGIC_IMPORTANCE
from roadmap import ROADMAP

# ----------------------------
# Logging
# ----------------------------
logger = logging.getLogger("hotel_tech_readiness")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Hotel Tech Readiness API", version="0.4.1")

# ----------------------------
# OpenAPI Models (important for GPT Actions)
# ----------------------------
class AnalyzeRequest(BaseModel):
    url: str
    competitor_url: str | None = None

    # Commercial assumptions (optional)
    rooms: int | None = None
    occupancy: float | None = None
    adr: float | None = None

    # Optional customer-confirmed systems (trust-first, improves confidence for private systems)
    pms_vendor: str | None = None
    booking_engine_vendor: str | None = None
    channel_manager_vendor: str | None = None
    crm_vendor: str | None = None


class AnalyzeResponse(BaseModel):
    analysis: Dict[str, Any] = Field(
        ...,
        description="Full structured analysis object (scores, detections, benchmarks, layers, roadmap, evidence, etc.).",
    )
    report_md: str = Field(..., description="C-suite report in Markdown.")


# ----------------------------
# Canonical layers
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

# detectors.yaml category mapping -> canonical layers
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
    "ibe": "Distribution",

    # Core systems
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
    "cdp": "Guest Data & CRM",

    # Tracking & attribution
    "tracking": "Commercial Execution",
    "analytics": "Commercial Execution",
    "attribution": "Commercial Execution",
    "tag manager": "Commercial Execution",
    "advertising": "Commercial Execution",
    "commercial execution": "Commercial Execution",

    # In-venue
    "in-venue": "In-Venue Experience",
    "in venue": "In-Venue Experience",
    "guest messaging": "In-Venue Experience",
    "digital check-in": "In-Venue Experience",
    "upsell": "In-Venue Experience",
    "wifi": "In-Venue Experience",
    "keys": "In-Venue Experience",

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
MAX_PAGES = 16
MAX_INTERNAL_LINKS = 14
MAX_REDIRECTS = 6
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


def map_category_to_layer(category: str) -> str:
    c = (category or "").strip().lower()
    if not c:
        return "Commercial Execution"
    if category in CANONICAL_LAYER_ORDER:
        return category
    return CATEGORY_TO_LAYER.get(c, "Commercial Execution")


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
    """
    Treat user-confirmed systems as high-confidence detections.
    """
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
# Segment inference (kept conservative)
# ----------------------------
_LUXURY_CUES = [
    "luxury", "five-star", "5-star", "spa", "suite", "heritage",
    "fine dining", "champagne", "afternoon tea",
]
_URBAN_CUES = [
    "city centre", "city center", "station", "minutes from", "walk to",
    "cathedral", "shopping", "business", "conference",
]


def infer_hotel_segment(public_text: str, url: str = "") -> Dict[str, Any]:
    text = (public_text or "").lower()
    u = (url or "").lower()

    evidence: List[str] = []
    luxury_hits = [c for c in _LUXURY_CUES if c in text]
    urban_hits = [c for c in _URBAN_CUES if (c in text) or (c in u)]

    if luxury_hits:
        evidence.append(f"Luxury cues: {', '.join(sorted(set(luxury_hits))[:6])}")
    if urban_hits:
        evidence.append(f"Urban/business cues: {', '.join(sorted(set(urban_hits))[:6])}")

    if luxury_hits and urban_hits:
        segment = "Upper-upscale / luxury city hotel"
        confidence = "Medium"
        implications = [
            "Multiple revenue centres likely → guest data fragmentation risk increases.",
            "Channel mix/attribution complexity typically higher → booking-flow measurement matters.",
            "Integration depth matters more than tool count → map data flows before vendor change.",
        ]
    elif luxury_hits:
        segment = "Upper-upscale independent hotel"
        confidence = "Low–Medium"
        implications = [
            "Premium positioning → direct mix and repeat behaviour are high-leverage.",
            "Identity resolution and CRM orchestration often under-utilised.",
            "Integration health is usually the constraint, not vendor choice.",
        ]
    else:
        segment = "Independent hotel"
        confidence = "Low"
        implications = [
            "Benchmark context should be broad; focus on measurement + distribution hygiene first.",
        ]

    if not evidence:
        evidence = ["No strong segment cues detected in sampled public text."]

    return {"segment": segment, "confidence": confidence, "evidence": evidence, "implications": implications}


# ----------------------------
# Evidence + crawl extraction
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
    if not s:
        return ""
    return s[:limit]


def _extract_jsonld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        for tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
            raw = (tag.string or "").strip()
            if not raw:
                continue
            import json
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    out.extend([x for x in data if isinstance(x, dict)])
                elif isinstance(data, dict):
                    out.append(data)
            except Exception:
                continue
    except Exception:
        pass
    return out


def _internal_links_from_soup(base_url: str, soup: BeautifulSoup, limit: int) -> List[str]:
    links: List[str] = []
    base_host = (urlparse(base_url).netloc or "").lower()

    def _good(href: str) -> bool:
        if not href:
            return False
        if href.startswith("#"):
            return False
        if href.startswith("mailto:") or href.startswith("tel:"):
            return False
        if href.lower().startswith("javascript:"):
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
        if abs_u not in links:
            links.append(abs_u)
        if len(links) >= limit:
            break
    return links


_BOOKING_KEYWORDS = [
    "book", "booking", "reserve", "reservation", "availability", "rooms", "check availability",
    "offers", "rates",
]


def _find_booking_candidates(base_url: str, soup: BeautifulSoup) -> List[str]:
    candidates: List[str] = []

    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        text = (a.get_text(" ", strip=True) or "").lower()
        href_l = href.lower()
        if any(k in text for k in _BOOKING_KEYWORDS) or any(k in href_l for k in _BOOKING_KEYWORDS):
            candidates.append(urljoin(base_url, href))

    for f in soup.find_all("form"):
        action = (f.get("action") or "").strip()
        if action and any(k in action.lower() for k in _BOOKING_KEYWORDS):
            candidates.append(urljoin(base_url, action))

    for i in soup.find_all("iframe"):
        src = (i.get("src") or "").strip()
        if src and any(k in src.lower() for k in _BOOKING_KEYWORDS):
            candidates.append(urljoin(base_url, src))

    seen = set()
    out: List[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:6]


async def _safe_get(client: httpx.AsyncClient, url: str) -> Tuple[Optional[PageResult], Optional[Dict[str, Any]]]:
    try:
        r = await client.get(url)
        ct = (r.headers.get("content-type") or "").lower()
        html = ""
        if ("text/html" in ct) or ("application/xhtml+xml" in ct) or ("text/plain" in ct) or ("application/xml" in ct) or ("text/xml" in ct):
            html = r.text or ""

        cookies = {}
        try:
            for k, v in r.cookies.items():
                if len(cookies) >= MAX_COOKIE_KEYS:
                    break
                cookies[str(k)] = str(v)
        except Exception:
            pass

        headers = {}
        try:
            for hk, hv in r.headers.items():
                if hk.lower() in {"server", "x-powered-by", "via", "x-cache", "cf-ray", "x-amz-cf-id"}:
                    headers[hk] = str(hv)
        except Exception:
            pass

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
    """
    Bounded crawl from a single URL:
    - homepage
    - robots.txt
    - sitemap.xml
    - top internal links (depth 1)
    - booking flow discovery (follow redirects)
    Returns structured signals object used for detection + evidence.
    """
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
        # 1) homepage
        home, err = await _safe_get(client, root_url)
        if err or not home:
            return {"root_url": root_url, "base": base, "pages": [], "errors": [err] if err else [], "booking_flow": {}, "evidence": {}}
        pages.append(home)

        # 2) robots + sitemap
        for p in [urljoin(base, "/robots.txt"), urljoin(base, "/sitemap.xml")]:
            if len(pages) >= MAX_PAGES:
                break
            pr, pe = await _safe_get(client, p)
            if pe:
                errors.append(pe)
            elif pr:
                pages.append(pr)

        # 3) internal links (depth 1)
        try:
            soup = BeautifulSoup(home.html or "", "lxml")
            internal = _internal_links_from_soup(root_url, soup, MAX_INTERNAL_LINKS)
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

        # 4) booking discovery
        booking_flow = {"candidates": [], "final_url": None, "final_domain": None, "evidence": []}
        try:
            soup_home = BeautifulSoup(home.html or "", "lxml")
            candidates = _find_booking_candidates(root_url, soup_home)
            booking_flow["candidates"] = candidates

            for pr in pages[:5]:
                if len(booking_flow["candidates"]) >= 6:
                    break
                if not pr.html:
                    continue
                sp = BeautifulSoup(pr.html, "lxml")
                extra = _find_booking_candidates(pr.url, sp)
                for c in extra:
                    if c not in booking_flow["candidates"]:
                        booking_flow["candidates"].append(c)
                    if len(booking_flow["candidates"]) >= 6:
                        break

            if booking_flow["candidates"]:
                candidate = booking_flow["candidates"][0]
                try:
                    r = await client.get(candidate, follow_redirects=True)
                    booking_flow["final_url"] = str(r.url)
                    booking_flow["final_domain"] = (urlparse(str(r.url)).netloc or "").lower()

                    chain = []
                    try:
                        for h in r.history:
                            chain.append(str(h.url))
                    except Exception:
                        pass
                    if chain:
                        booking_flow["evidence"].append({"type": "redirect_chain", "value": chain[:MAX_REDIRECTS]})

                    booking_flow["evidence"].append({"type": "booking_candidate", "value": candidate})
                    booking_flow["evidence"].append({"type": "booking_final_url", "value": booking_flow["final_url"]})

                    try:
                        cookie_keys = list(r.cookies.keys())[:MAX_COOKIE_KEYS]
                        if cookie_keys:
                            booking_flow["evidence"].append({"type": "booking_cookie_keys", "value": cookie_keys})
                    except Exception:
                        pass

                except Exception:
                    booking_flow["evidence"].append({"type": "booking_flow_error", "value": "Could not follow booking candidate."})
        except Exception:
            booking_flow = {"candidates": [], "final_url": None, "final_domain": None, "evidence": [{"type": "booking_flow_error", "value": "Booking discovery failed."}]}

    # Aggregate signals
    asset_urls: List[str] = []
    asset_domains: List[str] = []
    headers_union: Dict[str, str] = {}
    cookie_keys_union: List[str] = []
    jsonld_union: List[Dict[str, Any]] = []

    combined_parts: List[str] = []
    for pr in pages:
        if pr.headers:
            headers_union.update(pr.headers)

        if pr.cookies:
            for k in pr.cookies.keys():
                if k not in cookie_keys_union:
                    cookie_keys_union.append(k)
                    if len(cookie_keys_union) >= MAX_COOKIE_KEYS:
                        break

        html = pr.html or ""
        if html:
            combined_parts.append(html)
            try:
                soup = BeautifulSoup(html, "lxml")
                combined_parts.append(soup.get_text(" ", strip=True))

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

                jsonld_union.extend(_extract_jsonld(soup))
            except Exception:
                pass

    asset_domains = sorted(list({d for d in asset_domains if d}))
    asset_urls = list(dict.fromkeys(asset_urls))

    combined_blob = _truncate(" ".join(combined_parts), MAX_TEXT_CHARS)

    evidence = {
        "pages_fetched": [{"url": p.url, "status": p.status_code, "content_type": p.content_type} for p in pages[:MAX_PAGES]],
        "headers_observed": headers_union,
        "cookie_keys_observed": cookie_keys_union[:MAX_COOKIE_KEYS],
        "top_third_party_domains": asset_domains[:40],
        "booking_flow": booking_flow,
        "structured_data_snippets": _truncate(str(jsonld_union[:3]), 8000),
        "crawl_notes": [
            f"Bounded crawl: max_pages={MAX_PAGES}, max_internal_links={MAX_INTERNAL_LINKS}.",
            "No authentication, no form submission, no privileged access.",
        ],
        "crawl_errors": errors[:8],
    }

    return {
        "root_url": root_url,
        "base": base,
        "pages": pages,
        "asset_urls": asset_urls,
        "asset_domains": asset_domains,
        "headers": headers_union,
        "cookie_keys": cookie_keys_union[:MAX_COOKIE_KEYS],
        "booking_flow": booking_flow,
        "jsonld": jsonld_union,
        "blob": combined_blob,
        "evidence": evidence,
    }


# ----------------------------
# Layer summary (Observed / Inferred / Unresolved)
# ----------------------------
def _proof_path_for_layer(layer: str) -> List[str]:
    layer_l = (layer or "").lower()
    if "distribution" in layer_l:
        return [
            "Follow booking CTA links and capture final redirect domain (booking engine/CRS).",
            "Inspect iframe src and form actions on booking pages.",
            "Check cookies set during booking journey (often vendor-specific).",
        ]
    if "core" in layer_l:
        return [
            "PMS rarely visible publicly; infer via booking engine/CRS patterns and group affiliation.",
            "Check careers/vendor pages or staff portals linked publicly (occasionally reveal PMS).",
            "Confirm via reservation confirmation emails or check-in comms (not available from URL).",
        ]
    if "guest data" in layer_l or "crm" in layer_l:
        return [
            "Inspect newsletter forms and consent tooling (privacy/marketing vendors).",
            "Look for triggered lifecycle endpoints or email service domains.",
            "Check site scripts for CRM/CDP tags (Revinate/Cendyn etc.).",
        ]
    if "commercial" in layer_l:
        return [
            "Inspect scripts for GA4, Meta, Google Ads, metasearch tags.",
            "Check booking funnel events presence via booking domain signals.",
        ]
    if "in-venue" in layer_l:
        return [
            "Search site for 'mobile check-in', 'digital key', 'guest app', 'order' pages.",
            "Look for integrations referenced in FAQ/help pages.",
        ]
    if "operations" in layer_l:
        return [
            "Ops tools rarely visible publicly; check careers pages for operational tech mentions.",
            "Check for staff portal links in footer/legal pages.",
        ]
    if "finance" in layer_l:
        return [
            "BI/reporting not usually visible; infer from group patterns and presence of analytics maturity.",
            "Look for stakeholder portals, owner/investor pages if any.",
        ]
    return ["Review linked pages for vendor mentions and follow booking journey redirects."]


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
            likely_state = fallback.get("likely_state")
            typical_risk = fallback.get("typical_risk")

            if likely_state or typical_risk:
                summary[layer] = {
                    "visibility": "Inferred",
                    "visibility_state": "Inferred",
                    "strategic_importance": importance,
                    "importance_rationale": rationale,
                    "detections": [],
                    "likely_state": likely_state,
                    "typical_risk": typical_risk,
                    "proof_path": _proof_path_for_layer(layer),
                }
            else:
                summary[layer] = {
                    "visibility": "Unresolved",
                    "visibility_state": "Unresolved",
                    "strategic_importance": importance,
                    "importance_rationale": rationale,
                    "detections": [],
                    "likely_state": (
                        "This capability is commonly present in hotels, but cannot be inferred "
                        "with confidence from current public signals."
                    ),
                    "typical_risk": (
                        "Treat as an investigation item; lack of clarity itself creates operational "
                        "and commercial risk."
                    ),
                    "proof_path": _proof_path_for_layer(layer),
                }

    return summary


# ----------------------------
# Peer segment selection (stable for benchmarks)
# ----------------------------
def choose_peer_segment(url: str) -> str:
    return "lifestyle_boutique"


# ----------------------------
# Detection against aggregated signals
# ----------------------------
def detect_tools_from_signals(signals: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    detectors = load_detectors()
    blob = (signals.get("blob") or "")
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
        " ".join([f"{k}:{v}" for k, v in (headers or {}).items()]),
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
            if layer not in by_layer:
                layer = "Commercial Execution"
            by_layer[layer].append(det)

    return detections, by_layer


# ----------------------------
# Comparison (competitor)
# ----------------------------
def compute_comparison(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    try:
        a_score = (a.get("scores") or {}).get("overall_score_0_to_100")
        b_score = (b.get("scores") or {}).get("overall_score_0_to_100")
        delta = None
        if isinstance(a_score, (int, float)) and isinstance(b_score, (int, float)):
            delta = round(a_score - b_score, 1)

        def _layer_map(x):
            out = {}
            for item in (x.get("scores") or {}).get("layer_scores", []) or []:
                if isinstance(item, dict):
                    nm = item.get("layer") or item.get("name")
                    # supports scoring.py keys: score_0_to_5
                    sc = item.get("score_0_to_5")
                    if sc is None:
                        sc = item.get("score") if item.get("score") is not None else item.get("value")
                    if nm is not None:
                        out[str(nm)] = sc
            return out

        a_layers = _layer_map(a)
        b_layers = _layer_map(b)

        layer_deltas = []
        for k in CANONICAL_LAYER_ORDER:
            if k in a_layers and k in b_layers and isinstance(a_layers[k], (int, float)) and isinstance(b_layers[k], (int, float)):
                layer_deltas.append({"layer": k, "delta_0_to_5": round(a_layers[k] - b_layers[k], 2)})

        a_book = (((a.get("evidence") or {}).get("booking_flow") or {}).get("final_domain"))
        b_book = (((b.get("evidence") or {}).get("booking_flow") or {}).get("final_domain"))

        return {
            "score_delta_0_to_100": delta,
            "layer_deltas": layer_deltas,
            "booking_engine_domain_a": a_book,
            "booking_engine_domain_b": b_book,
            "notes": [
                "Comparison uses identical bounded public-signal scan logic for both hotels.",
                "Differences reflect visibility and booking-journey plumbing, not internal system quality.",
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
# Fallback response
# ----------------------------
def fallback_response(error: Dict[str, Any], model_inputs: Dict[str, Any], url: Optional[str] = None) -> Dict[str, Any]:
    try:
        opp = opportunity_model(model_inputs)
    except Exception as e:
        opp = {
            "assumptions": {"rooms": 60, "occupancy": 0.72, "adr": 140},
            "annual_opportunity_gbp_range": [0, 0],
            "error": f"opportunity_model failed: {str(e)}",
        }

    peer_segment = choose_peer_segment(url or "")
    benchmark = PEER_BENCHMARKS.get(peer_segment, PEER_BENCHMARKS["lifestyle_boutique"])

    empty_by_layer = {layer: [] for layer in CANONICAL_LAYER_ORDER}
    layers = build_layer_summary(empty_by_layer)

    analysis = {
        "url": url,
        "detections": [],
        "scores": {"overall_score_0_to_100": None, "layer_scores": []},
        "benchmarks": {
            "segment": peer_segment,
            "typical_range": list(benchmark["typical_range"]),
            "best_in_class": benchmark["best_in_class"],
            "interpretation": "Score unavailable due to limited public signals.",
        },
        "segment_inference": {"segment": "Unresolved", "confidence": "Low", "evidence": [], "implications": []},
        "layers": layers,
        "roadmap": ROADMAP,
        "opportunity": opp,
        "evidence": {"crawl_errors": [error]},
        "notes": [
            "Public technology signals could not be processed for this website at this time.",
            "This may be due to bot protection, heavy JavaScript, rate limits, or an internal processing edge case.",
            "You can optionally confirm PMS/booking engine/CRM to tighten confidence.",
        ],
        "error": error,
    }

    try:
        report_md = render_report_md(analysis)
    except Exception:
        report_md = (
            "# Hotel Technology & Revenue Readiness Assessment\n\n"
            "We couldn’t complete the scan just now. This does not indicate a problem with your systems.\n"
        )

    return {"analysis": analysis, "report_md": report_md}


# ----------------------------
# Main endpoint
# ----------------------------
@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """
    Hard guarantee: never throws, never returns 500.
    Always returns HTTP 200 with an analysis object (and best-effort report).
    """
    url = normalise_url(req.url)
    competitor_url = normalise_url(req.competitor_url) if req.competitor_url else None
    model_inputs = {"rooms": req.rooms, "occupancy": req.occupancy, "adr": req.adr}

    try:
        # ---- Run primary scan
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
            scores = {"overall_score_0_to_100": None, "layer_scores": [], "error": f"score_layers failed: {str(e)}"}

        try:
            opp = opportunity_model(model_inputs)
        except Exception as e:
            logger.error("ERROR in opportunity_model:\n%s", traceback.format_exc())
            opp = {
                "assumptions": {"rooms": 60, "occupancy": 0.72, "adr": 140},
                "annual_opportunity_gbp_range": [0, 0],
                "error": f"opportunity_model failed: {str(e)}",
            }

        peer_segment = choose_peer_segment(url)
        benchmark = PEER_BENCHMARKS.get(peer_segment, PEER_BENCHMARKS["lifestyle_boutique"])
        score_text = interpret_score(scores.get("overall_score_0_to_100"), benchmark)

        layers = build_layer_summary(by_layer)

        sample_text = (signals.get("blob") or "")[:80_000]
        segment_inference = infer_hotel_segment(public_text=sample_text, url=url)

        confirmations = {
            "pms_vendor": req.pms_vendor,
            "booking_engine_vendor": req.booking_engine_vendor,
            "channel_manager_vendor": req.channel_manager_vendor,
            "crm_vendor": req.crm_vendor,
        }
        confirmations_provided = {k: v for k, v in confirmations.items() if v}

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
            "layers": layers,
            "roadmap": ROADMAP,
            "opportunity": opp,
            "evidence": signals.get("evidence") or {},
            "confirmations": {
                "provided": confirmations_provided,
                "note": "Confirmed systems are treated as confirmed detections with source='customer_confirmed'.",
            },
            "notes": [
                "This assessment uses bounded public-signal crawling (homepage + internal links + booking flow where discoverable).",
                "Visibility states are Observed/Inferred/Unresolved; lack of observation does not imply absence.",
                "Vendor-neutral by design; examples are illustrative, not recommendations.",
            ],
        }

        # ---- Competitor scan + comparison (optional)
        if competitor_url:
            try:
                comp_signals = await crawl_site_signals(competitor_url)
                comp_dets, comp_by_layer = detect_tools_from_signals(comp_signals)
                comp_layers = build_layer_summary(comp_by_layer)

                try:
                    comp_scores = score_layers(comp_by_layer)
                except Exception:
                    comp_scores = {"overall_score_0_to_100": None, "layer_scores": [], "error": "score_layers_failed"}

                comp_peer_segment = choose_peer_segment(competitor_url)
                comp_benchmark = PEER_BENCHMARKS.get(comp_peer_segment, PEER_BENCHMARKS["lifestyle_boutique"])
                comp_score_text = interpret_score(comp_scores.get("overall_score_0_to_100"), comp_benchmark)

                competitor_analysis = {
                    "url": competitor_url,
                    "detections": comp_dets,
                    "scores": comp_scores,
                    "benchmarks": {
                        "segment": comp_peer_segment,
                        "typical_range": list(comp_benchmark["typical_range"]),
                        "best_in_class": comp_benchmark["best_in_class"],
                        "interpretation": comp_score_text,
                    },
                    "layers": comp_layers,
                    "evidence": comp_signals.get("evidence") or {},
                }

                analysis["competitor"] = competitor_analysis
                analysis["comparison"] = compute_comparison(analysis, competitor_analysis)
            except Exception:
                logger.error("Competitor scan failed:\n%s", traceback.format_exc())
                analysis["comparison"] = {"error": "competitor_scan_failed", "notes": ["Competitor scan could not be completed safely."]}

        try:
            report_md = render_report_md(analysis)
        except TypeError:
            report_md = render_report_md({"scores": scores, "opportunity": opp})
        except Exception as e:
            logger.error("ERROR in render_report_md:\n%s", traceback.format_exc())
            report_md = (
                "# Hotel Technology & Revenue Readiness Assessment\n\n"
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
