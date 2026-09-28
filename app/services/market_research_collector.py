"""MarketResearchCollector v2 — Evidence-Based Market Intelligence.

Real sources collected by this agent:
  1. Remotive API   (https://remotive.com/api/remote-jobs)  — remote tech jobs
  2. Arbeitnow API  (https://www.arbeitnow.com/api/job-board-api) — EU tech jobs
  3. ArXiv API      (http://export.arxiv.org/api/query) — research publications
  4. DuckDuckGo     (duckduckgo_search library) — web articles & reports

Human verification links only (NOT collected by the agent — labelled explicitly):
  - LinkedIn Jobs search page
  - Google Trends

Design principles:
  - If a source fails: log, mark failed, continue — never fabricate
  - Return EvidenceItem objects, not raw numbers
  - Normalize all signals to 0-100 after collection
"""
from __future__ import annotations

import math
import urllib.request
import urllib.parse
import urllib.error
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

from app.core.logging import get_logger
from app.models.evidence import (
    CourseEvidence, EvidenceItem, MarketSignals, SourceStatus
)

logger = get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
_HTTP_TIMEOUT = 10  # seconds
_DDG_MAX_RESULTS = 5
_JOB_API_MAX = 20

# Stop words for keyword extraction
_STOP_WORDS = {
    "and", "or", "the", "a", "an", "in", "on", "of", "to", "for", "with",
    "how", "using", "deploy", "design", "build", "learn", "master",
    "introduction", "advanced", "practical", "complete", "course",
    "training", "bootcamp", "certified", "certification"
}


# ── Keyword Generator ──────────────────────────────────────────────────────
def generate_keywords(course_title: str, category: str = "") -> List[str]:
    """Generate search keywords from course title without hardcoding.
    
    Strategy:
    1. Extract meaningful tokens from title
    2. Build compound keywords (bigrams)
    3. Add category context
    Returns a deduplicated list of up to 5 keywords.
    """
    # Known compound tech terms to preserve
    COMPOUNDS = [
        "multi-agent", "unreal engine", "3ds max", "fusion 360",
        "virtual reality", "augmented reality", "web development",
        "game development", "product design", "architectural design",
        "digital avatar", "fashion design", "vibe coding", "ai systems",
        "machine learning", "deep learning"
    ]
    lower = course_title.lower()
    keywords = []

    # Priority: check for known compound terms first
    for compound in COMPOUNDS:
        if compound in lower:
            keywords.append(compound)

    # Add individual significant tokens
    tokens = [
        w.strip(".,;:!?-") for w in lower.split()
        if len(w) > 3 and w.lower() not in _STOP_WORDS
    ]
    for token in tokens:
        if token not in keywords and len(token) > 3:
            keywords.append(token)

    # Add category if useful
    if category and category.lower() not in [k.lower() for k in keywords]:
        keywords.append(category.lower())

    # Deduplicate preserving order, limit to 5
    seen = set()
    result = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result[:5]


# ── HTTP Helper ────────────────────────────────────────────────────────────
def _fetch_json(url: str, timeout: int = _HTTP_TIMEOUT) -> Optional[dict | list]:
    """Fetch JSON from a URL. Returns None on failure."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "DigiArt-MarketAgent/2.0 (education research)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        logger.warning(f"HTTP fetch failed for {url}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Parse failed for {url}: {e}")
        return None


def _compute_freshness(date_str: Optional[str]) -> str:
    """Classify evidence freshness based on publication date."""
    if not date_str:
        return "unknown"
    try:
        # Try common date formats
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(date_str[:19], fmt[:len(date_str[:19])])
                dt = dt.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - dt
                if age < timedelta(days=30):
                    return "fresh"
                elif age < timedelta(days=90):
                    return "recent"
                else:
                    return "older"
            except ValueError:
                continue
    except Exception:
        pass
    return "unknown"


# ── Source 1: Remotive API ─────────────────────────────────────────────────
def collect_remotive(course_id: str, keyword: str) -> Tuple[List[EvidenceItem], SourceStatus]:
    """Remotive.com public API — real remote tech job listings.
    Returns (items, status).
    """
    tag = urllib.parse.quote(keyword.split()[0].lower())
    url = f"https://remotive.com/api/remote-jobs?search={urllib.parse.quote(keyword)}&limit={_JOB_API_MAX}"
    now = datetime.now(timezone.utc).isoformat()
    
    data = _fetch_json(url)
    if data is None:
        return [], SourceStatus(source="remotive", success=False, error="fetch failed", label="FAILED")

    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    items = []
    for job in jobs[:_JOB_API_MAX]:
        pub_raw = job.get("publication_date", "")
        pub = str(pub_raw) if pub_raw else ""
        items.append(EvidenceItem(
            course_id=course_id,
            source="remotive",
            title=job.get("title", ""),
            url=job.get("url", ""),
            snippet=f"{job.get('company_name', '')} — {job.get('candidate_required_location', 'Remote')}",
            published_at=pub,
            retrieved_at=now,
            signal_type="job",
            reliability=0.85,
            freshness=_compute_freshness(pub),
        ))

    status = SourceStatus(
        source="remotive",
        success=True,
        count=len(items),
        retrieved_at=now,
        label="COLLECTED"
    )
    logger.info(f"[Collector] Remotive: {len(items)} jobs for '{keyword}'")
    return items, status


# ── Source 2: Arbeitnow API ────────────────────────────────────────────────
def collect_arbeitnow(course_id: str, keyword: str) -> Tuple[List[EvidenceItem], SourceStatus]:
    """Arbeitnow public job board API — EU tech job listings."""
    url = f"https://www.arbeitnow.com/api/job-board-api?search={urllib.parse.quote(keyword)}"
    now = datetime.now(timezone.utc).isoformat()

    data = _fetch_json(url)
    if data is None:
        return [], SourceStatus(source="arbeitnow", success=False, error="fetch failed", label="FAILED")

    jobs = data.get("data", []) if isinstance(data, dict) else []
    items = []
    for job in jobs[:_JOB_API_MAX]:
        pub_raw = job.get("created_at", "")
        pub = str(pub_raw) if pub_raw else ""
        items.append(EvidenceItem(
            course_id=course_id,
            source="arbeitnow",
            title=job.get("title", ""),
            url=job.get("url", f"https://www.arbeitnow.com/jobs/{job.get('slug', '')}"),
            snippet=job.get("description", "")[:200],
            published_at=pub,
            retrieved_at=now,
            signal_type="job",
            reliability=0.80,
            freshness=_compute_freshness(pub),
        ))

    status = SourceStatus(
        source="arbeitnow",
        success=True,
        count=len(items),
        retrieved_at=now,
        label="COLLECTED"
    )
    logger.info(f"[Collector] Arbeitnow: {len(items)} jobs for '{keyword}'")
    return items, status


# ── Source 3: ArXiv API ────────────────────────────────────────────────────
def collect_arxiv(course_id: str, keyword: str) -> Tuple[List[EvidenceItem], SourceStatus, int]:
    """ArXiv API — academic research publications. Returns (items, status, total_count)."""
    now = datetime.now(timezone.utc).isoformat()
    encoded = urllib.parse.quote(f'"{keyword}"')
    url = f"http://export.arxiv.org/api/query?search_query=all:{encoded}&start=0&max_results=5&sortBy=submittedDate&sortOrder=descending"
    count_url = f"http://export.arxiv.org/api/query?search_query=all:{encoded}&start=0&max_results=1"
    web_url = f"https://arxiv.org/search/?query={urllib.parse.quote(keyword)}&searchtype=all"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DigiArt-MarketAgent/2.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            root = ET.fromstring(resp.read())
    except Exception as e:
        logger.warning(f"[Collector] ArXiv failed for '{keyword}': {e}")
        return [], SourceStatus(
            source="arxiv", success=False, error=str(e), label="FAILED",
            retrieved_at=now
        ), 0

    ns = "{http://www.w3.org/2005/Atom}"
    ons = "{http://a9.com/-/spec/opensearch/1.1/}"
    total_el = root.find(f"{ons}totalResults")
    total_count = int(total_el.text) if total_el is not None else 0

    items = []
    for entry in root.findall(f"{ns}entry"):
        title_el = entry.find(f"{ns}title")
        id_el = entry.find(f"{ns}id")
        pub_el = entry.find(f"{ns}published")
        summary_el = entry.find(f"{ns}summary")
        title = title_el.text.strip() if title_el is not None else ""
        url_val = id_el.text.strip() if id_el is not None else web_url
        pub = pub_el.text.strip() if pub_el is not None else ""
        snippet = (summary_el.text or "").strip()[:300] if summary_el is not None else ""
        items.append(EvidenceItem(
            course_id=course_id,
            source="arxiv",
            title=title,
            url=url_val,
            snippet=snippet,
            published_at=pub,
            retrieved_at=now,
            signal_type="research",
            reliability=0.90,
            freshness=_compute_freshness(pub),
        ))

    status = SourceStatus(
        source="arxiv", success=True, count=total_count,
        retrieved_at=now, label="COLLECTED"
    )
    logger.info(f"[Collector] ArXiv: {total_count} papers for '{keyword}'")
    return items, status, total_count


# ── Source 4: DuckDuckGo ───────────────────────────────────────────────────
def collect_duckduckgo(course_id: str, keyword: str) -> Tuple[List[EvidenceItem], SourceStatus]:
    """DuckDuckGo search — web articles, reports, industry news."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        from duckduckgo_search import DDGS
        query = f"{keyword} job market demand 2025 trend industry"
        results = list(DDGS().text(query, max_results=_DDG_MAX_RESULTS))
    except Exception as e:
        logger.warning(f"[Collector] DuckDuckGo failed for '{keyword}': {e}")
        return [], SourceStatus(source="duckduckgo", success=False, error=str(e), label="FAILED", retrieved_at=now)

    if not results:
        return [], SourceStatus(source="duckduckgo", success=False, error="no results", label="FAILED", retrieved_at=now)

    items = []
    for r in results:
        items.append(EvidenceItem(
            course_id=course_id,
            source="duckduckgo",
            title=r.get("title", ""),
            url=r.get("href", r.get("link", "")),
            snippet=r.get("body", "")[:400],
            published_at=None,
            retrieved_at=now,
            signal_type="web",
            reliability=0.65,
            freshness="unknown",
        ))

    status = SourceStatus(
        source="duckduckgo", success=True, count=len(items),
        retrieved_at=now, label="COLLECTED"
    )
    logger.info(f"[Collector] DuckDuckGo: {len(items)} results for '{keyword}'")
    return items, status


# ── Signal Normalizer ──────────────────────────────────────────────────────
def compute_signals(evidence: CourseEvidence, arxiv_total: int) -> MarketSignals:
    """Compute normalized 0-100 signals from collected evidence.

    Market Demand = 0.50×job_signal + 0.30×web_signal + 0.20×research_signal
    Industry Trend = proxy from publication growth + freshness of results
    """
    job_items = [i for i in evidence.items if i.signal_type == "job"]
    web_items = [i for i in evidence.items if i.signal_type == "web"]
    research_items = [i for i in evidence.items if i.signal_type == "research"]

    # Normalize job count: 0 jobs=0, 20+ jobs=100
    job_count = len(job_items)
    job_signal = min(job_count / 20 * 100, 100.0)

    # Normalize web count: 0=0, 5+=100
    web_count = len(web_items)
    web_signal = min(web_count / 5 * 100, 100.0)

    # Normalize ArXiv: log scale (0=0, 1000+=100)
    research_signal = 0.0
    if arxiv_total > 0:
        research_signal = min(math.log10(arxiv_total + 1) / math.log10(1001) * 100, 100.0)

    return MarketSignals(
        job_signal=round(job_signal, 1),
        research_signal=round(research_signal, 1),
        web_signal=round(web_signal, 1),
        job_count=job_count,
        arxiv_count=arxiv_total,
        web_count=web_count,
        keywords=evidence.keywords,
    )


# ── Main Collector Class ───────────────────────────────────────────────────
class MarketResearchCollector:
    """Orchestrates all evidence collection for a single course."""

    def collect(self, course_id: str, course_title: str, category: str) -> CourseEvidence:
        """Collect all evidence. Never raises — sources fail gracefully."""
        keywords = generate_keywords(course_title, category)
        primary_kw = keywords[0] if keywords else course_title

        evidence = CourseEvidence(
            course_id=course_id,
            title=course_title,
            keywords=keywords,
        )

        # Source 1: Remotive
        items, status = collect_remotive(course_id, primary_kw)
        evidence.items.extend(items)
        evidence.source_statuses.append(status)

        # Source 2: Arbeitnow
        items, status = collect_arbeitnow(course_id, primary_kw)
        evidence.items.extend(items)
        evidence.source_statuses.append(status)

        # Source 3: ArXiv
        items, status, arxiv_total = collect_arxiv(course_id, primary_kw)
        evidence.items.extend(items)
        evidence.source_statuses.append(status)

        # Source 4: DuckDuckGo
        items, status = collect_duckduckgo(course_id, primary_kw)
        evidence.items.extend(items)
        evidence.source_statuses.append(status)

        # Add human verification links (NOT collected, labelled explicitly)
        evidence.source_statuses.append(SourceStatus(
            source="linkedin",
            success=False,
            label="HUMAN_VERIFICATION",
            retrieved_at=None,
        ))
        evidence.source_statuses.append(SourceStatus(
            source="google_trends",
            success=False,
            label="HUMAN_VERIFICATION",
            retrieved_at=None,
        ))

        # Compute signals
        evidence.signals = compute_signals(evidence, arxiv_total)

        return evidence
