"""MarketIntelligenceService v2 — LLM Analyst.

Receives raw collected EvidenceItems and tasks the LLM with analyzing them
to extract market_demand and industry_trend. Does NOT allow the LLM to invent
evidence or calculate the final recommendation score.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from app.core.logging import get_logger
from app.llm.base_provider import LLMProvider
from app.repositories.agenda_repository import AgendaRepository
from app.services.market_research_collector import MarketResearchCollector
from app.models.evidence import CourseEvidence, LLMAnalysis, EVIDENCE_STORE

logger = get_logger(__name__)

_PREFERRED_MODELS = ["qwen2.5:1.5b", "mistral:latest", "llama3:latest"]

# System prompt — no curly braces, so safe with any .format() approach.
_SYSTEM_PROMPT = "You are a strict data extraction AI. Output only valid JSON, no markdown, no prose."

# Prompt header template — only placeholders here, NO example JSON with braces.
# The JSON example is appended separately as a plain string to avoid .format() KeyError
# when snippet text contains { } characters (e.g. job titles, URLs with query strings).
_PROMPT_HEADER = """\
You are a Market Intelligence Analyst evaluating a training course.
Analyze the following REAL collected evidence.

COURSE: {title}
KEYWORDS: {keywords}

1. RAW JOB MARKET SIGNAL (Score: {job_signal}/100)
{job_snippets}

2. RAW WEB SIGNAL (Score: {web_signal}/100)
{web_snippets}

3. RAW RESEARCH SIGNAL (Score: {research_signal}/100)
{research_snippets}

YOUR TASK:
Based STRICTLY on the evidence above, estimate:
1. market_demand (0-100): current employer hiring volume based on job/web signals.
2. industry_trend (0-100): momentum and growth based on research/web signals.
3. confidence (0.0-1.0): your confidence in these numbers given the provided text.
4. summary: ONE SENTENCE explaining why this is relevant to employers.
5. signals: Array of 1 to 3 short strings highlighting key evidence points.

If there is insufficient evidence, return null for demand/trend and note "Insufficient evidence".

OUTPUT STRICTLY VALID JSON (no markdown fences):
"""

# Appended after header — plain string, not passed through .format()
_PROMPT_JSON_EXAMPLE = """\
{"market_demand": 85, "industry_trend": 92, "confidence": 0.85, "summary": "Strong demand shown by 25+ remote listings.", "signals": ["Frequent job postings", "High research volume"], "analysis_note": "Data looks strong."}
"""


class MarketIntelligenceService:
    def __init__(self, llm_provider: LLMProvider, agenda_repo: AgendaRepository):
        self.llm = llm_provider
        self.agenda_repo = agenda_repo
        self.collector = MarketResearchCollector()

    def _detect_best_model(self) -> str:
        import urllib.request
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as resp:
                tags = json.loads(resp.read().decode())
            available = {m["name"] for m in tags.get("models", [])}
            for m in _PREFERRED_MODELS:
                if m in available:
                    return m
        except Exception:
            pass
        return "qwen2.5:1.5b"

    def _format_snippets(self, evidence: CourseEvidence, signal_type: str, max_chars: int = 500) -> str:
        """Return a plain-text snippet block for the given signal type.
        We deliberately truncate and strip any { } chars so the text
        never interferes with Python string formatting in callers.
        """
        if signal_type == "research":
            items = evidence.get_items_by_source("arxiv")
        elif signal_type == "job":
            items = (
                evidence.get_items_by_source("remotive")
                + evidence.get_items_by_source("arbeitnow")
            )
        else:  # web
            items = evidence.get_items_by_source("duckduckgo")

        if not items:
            return "No data collected."

        lines = []
        for i in items[:8]:  # cap at 8 items
            line = f"- {i.title}: {i.snippet}"
            # Strip curly braces so they cannot confuse .format() downstream
            line = line.replace("{", "(").replace("}", ")")
            lines.append(line)

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text

    def _build_prompt(self, evidence: CourseEvidence) -> str:
        """Build the LLM prompt safely.

        IMPORTANT: We pre-escape the snippet text (curly braces replaced) so
        that str.format() on _PROMPT_HEADER cannot raise KeyError from snippet
        content that happens to look like a template placeholder.
        """
        header = _PROMPT_HEADER.format(
            title=evidence.title.replace("{", "(").replace("}", ")"),
            keywords=", ".join(
                k.replace("{", "(").replace("}", ")") for k in evidence.keywords
            ),
            job_signal=getattr(evidence.signals, "job_signal", 0) if evidence.signals else 0,
            web_signal=getattr(evidence.signals, "web_signal", 0) if evidence.signals else 0,
            research_signal=getattr(evidence.signals, "research_signal", 0) if evidence.signals else 0,
            job_snippets=self._format_snippets(evidence, "job"),
            web_snippets=self._format_snippets(evidence, "web"),
            research_snippets=self._format_snippets(evidence, "research"),
        )
        return header + _PROMPT_JSON_EXAMPLE

    def _analyze_evidence(self, evidence: CourseEvidence, model: str) -> LLMAnalysis:
        """Ask LLM to extract meaning from the raw snippets."""
        if not evidence.signals:
            return LLMAnalysis(analysis_note="No signals collected")

        try:
            prompt = self._build_prompt(evidence)
        except Exception as e:
            logger.error(f"[MarketIntelligence] Prompt build failed for {evidence.course_id}: {e}")
            return LLMAnalysis(analysis_note=f"Prompt build error: {e}")

        try:
            response = self.llm.generate(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt,
                max_tokens=300,
                temperature=0.1,
            )
            raw_text = response.text.strip()

            # Strip markdown fences if model wrapped the JSON
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            raw_text = raw_text.strip()

            # Extract the JSON object (handles surrounding prose)
            if "{" in raw_text and "}" in raw_text:
                raw_text = raw_text[raw_text.find("{") : raw_text.rfind("}") + 1]

            data = json.loads(raw_text)

            if not isinstance(data, dict):
                raise ValueError(f"LLM returned {type(data).__name__}, expected dict")

            return LLMAnalysis(
                market_demand=data.get("market_demand"),
                industry_trend=data.get("industry_trend"),
                confidence=float(data.get("confidence", 0.5)),
                summary=str(data.get("summary", "")),
                signals=list(data.get("signals", [])),
                analysis_note=str(data.get("analysis_note", "")),
            )
        except Exception as e:
            logger.error(f"[MarketIntelligence] LLM parsing failed for {evidence.course_id}: {e}")
            return LLMAnalysis(analysis_note=f"LLM error: {e}")

    async def refresh_all_market_trends(self) -> Dict[str, Any]:
        """Triggered by the UI. Collects data and updates Google Sheets.

        Returns a dict containing:
          status, total_processed, model_used, processed, errors, results
        so the frontend toast can display per-course details.
        """
        import asyncio
        loop = asyncio.get_running_loop()
        courses = self.agenda_repo.get_all_courses()
        model = await loop.run_in_executor(None, self._detect_best_model)

        ws = self.agenda_repo._get_tab("Market_Trends")
        headers = ws.row_values(1)

        col_demand = headers.index("Market Demand") + 1
        col_trend = headers.index("Industry Trend") + 1
        col_notes = headers.index("Notes") + 1

        # Check for new columns, create if they don't exist
        new_cols: Dict[str, int] = {}
        for name in ("Confidence", "Evidence Count", "Last Updated", "Source URLs"):
            if name in headers:
                new_cols[name] = headers.index(name) + 1
            else:
                ws.update_cell(1, len(headers) + 1, name)
                headers.append(name)
                new_cols[name] = len(headers)

        # Safe row lookup: read col-A (Course ID) only to avoid matching
        # JSON text that may be stored in the Notes column.
        col_a_values = ws.col_values(1)
        course_row_map: Dict[str, int] = {}
        for i, val in enumerate(col_a_values):
            if val and val.strip() not in ("", "Course ID"):
                course_row_map[val.strip()] = i + 1

        total = 0
        errors = 0
        results: List[Dict[str, Any]] = []

        for course in courses:
            if course.status != "active":
                continue

            try:
                # 1. Collect real evidence
                evidence = await loop.run_in_executor(
                    None,
                    lambda c=course: self.collector.collect(c.course_id, c.title, c.category),
                )

                # 2. Store immediately so /evidence endpoint works even if LLM fails
                EVIDENCE_STORE[course.course_id] = evidence

                # 3. LLM Analysis
                analysis = await loop.run_in_executor(
                    None,
                    lambda ev=evidence: self._analyze_evidence(ev, model),
                )
                evidence.llm_analysis = analysis

                # 4. Resolve final scores (LLM → signal fallback → neutral)
                if analysis.market_demand is not None:
                    demand = max(0.0, min(100.0, float(analysis.market_demand)))
                    trend = max(0.0, min(100.0, float(analysis.industry_trend or 50.0)))
                    conf = float(analysis.confidence)
                elif evidence.signals:
                    sig = evidence.signals
                    demand = round(
                        0.50 * sig.job_signal
                        + 0.30 * sig.web_signal
                        + 0.20 * sig.research_signal,
                        1,
                    )
                    trend = round(0.60 * sig.research_signal + 0.40 * sig.web_signal, 1)
                    n_ok = len([s for s in evidence.source_statuses if s.success])
                    conf = round(min(n_ok / 4.0, 1.0) * 0.7, 2)
                else:
                    demand, trend, conf = 50.0, 50.0, 0.15

                summary = analysis.summary or f"Collected {evidence.total_count()} evidence items."
                urls = "; ".join(
                    f"{s.source}({'OK' if s.success else 'FAIL'})"
                    for s in evidence.source_statuses
                )

                # 5. Write to sheet using safe row lookup
                row = course_row_map.get(course.course_id)
                if row:
                    ws.update_cell(row, col_demand, int(demand))
                    ws.update_cell(row, col_trend, int(trend))
                    ws.update_cell(row, col_notes, summary[:500])
                    ws.update_cell(row, new_cols["Confidence"], round(conf, 3))
                    ws.update_cell(row, new_cols["Evidence Count"], evidence.total_count())
                    ws.update_cell(row, new_cols["Last Updated"], evidence.collected_at[:10])
                    ws.update_cell(row, new_cols["Source URLs"], urls[:300])
                else:
                    logger.warning(
                        f"[MI] Course {course.course_id} not found in Market_Trends col-A — skipping write"
                    )

                logger.info(
                    f"[MI] ✓ {course.course_id} demand={demand} trend={trend} "
                    f"conf={conf} evidence={evidence.total_count()}"
                )

                # Accumulate result for frontend toast
                results.append({
                    "course_id": course.course_id,
                    "title": course.title,
                    "market_demand": int(demand),
                    "industry_trend": int(trend),
                    "confidence": round(conf, 2),
                    "summary": summary,
                    "evidence_count": evidence.total_count(),
                })
                total += 1

            except Exception as e:
                logger.error(
                    f"[MI] Error processing {course.course_id}: {e}", exc_info=True
                )
                errors += 1

        # Invalidate caches so /recommendations reflects new scores immediately
        self.agenda_repo.invalidate_market_cache()

        return {
            "status": "success",
            "total_processed": total,
            # Fields consumed by the frontend toast:
            "model_used": model,
            "processed": total,
            "errors": errors,
            "results": results,
        }
