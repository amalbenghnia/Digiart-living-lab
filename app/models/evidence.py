"""Evidence models for the Market Intelligence Agent.

An EvidenceItem represents a single piece of data collected from a real
external source. The EvidenceStore holds all evidence for all courses
in memory during a market refresh cycle.

Design principle: never fabricate evidence. If a source fails, mark it
failed and continue with reduced confidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    """A single piece of evidence collected from a real external source."""
    course_id: str
    source: str              # "arxiv" | "remotive" | "arbeitnow" | "duckduckgo"
    title: str
    url: str
    snippet: str = ""
    published_at: Optional[str] = None
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signal_type: str = "web"   # "research" | "job" | "web"
    reliability: float = 0.75  # 0.0 - 1.0
    freshness: str = "unknown" # "fresh" (<30d) | "recent" (30-90d) | "older" (>90d)


class SourceStatus(BaseModel):
    """Status of a single collection source attempt."""
    source: str
    success: bool
    count: int = 0              # number of results collected
    error: Optional[str] = None
    retrieved_at: Optional[str] = None
    label: str = "COLLECTED"    # "COLLECTED" | "HUMAN_VERIFICATION" | "FAILED" | "NOT_QUERIED"


class MarketSignals(BaseModel):
    """Normalized signals computed from collected evidence."""
    job_signal: float = 0.0        # 0-100, from job APIs
    research_signal: float = 0.0  # 0-100, from ArXiv
    web_signal: float = 0.0       # 0-100, from DuckDuckGo
    job_count: int = 0            # raw number of job results
    arxiv_count: int = 0          # raw ArXiv paper count
    web_count: int = 0            # raw web result count
    keywords: List[str] = Field(default_factory=list)


class LLMAnalysis(BaseModel):
    """Structured output from the LLM analyst.
    
    The LLM receives real collected text and returns these indicators.
    market_demand and industry_trend can be None if evidence is insufficient.
    """
    market_demand: Optional[float] = None    # 0-100 or None
    industry_trend: Optional[float] = None  # 0-100 or None
    confidence: float = 0.20                # 0.0 - 1.0
    summary: str = ""
    signals: List[str] = Field(default_factory=list)
    analysis_note: str = ""  # "Insufficient evidence" etc.


class CourseEvidence(BaseModel):
    """All evidence and derived indicators for a single course."""
    course_id: str
    title: str
    keywords: List[str] = Field(default_factory=list)
    items: List[EvidenceItem] = Field(default_factory=list)
    source_statuses: List[SourceStatus] = Field(default_factory=list)
    signals: Optional[MarketSignals] = None
    llm_analysis: Optional[LLMAnalysis] = None
    collected_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def add_item(self, item: EvidenceItem) -> None:
        self.items.append(item)

    def get_items_by_source(self, source: str) -> List[EvidenceItem]:
        return [i for i in self.items if i.source == source]

    def total_count(self) -> int:
        return len(self.items)

    def confidence(self) -> float:
        """Compute confidence from number of sources and their quality."""
        if self.llm_analysis:
            return self.llm_analysis.confidence
        successful = [s for s in self.source_statuses if s.success]
        if not successful:
            return 0.15
        avg_rel = sum(
            i.reliability for i in self.items
        ) / max(len(self.items), 1)
        source_factor = min(len(successful) / 4, 1.0)  # max 4 sources
        return round(min(avg_rel * source_factor, 1.0), 2)


# In-memory store: course_id → CourseEvidence
# Populated during /market/refresh, served by /market/evidence/{course_id}
EVIDENCE_STORE: Dict[str, CourseEvidence] = {}
