import pytest
from app.services.market_research_collector import generate_keywords
from app.models.evidence import CourseEvidence, EvidenceItem
from app.services.market_research_collector import compute_signals

def test_keyword_generation():
    keywords = generate_keywords("Design and Deploy Multi-Agent AI Systems", "Tech")
    assert "multi-agent" in [k.lower() for k in keywords]
    assert len(keywords) <= 5

def test_signal_normalization():
    ev = CourseEvidence(course_id="C001", title="Test", keywords=[])
    # Give it 20 jobs (max job signal 100)
    for _ in range(20):
        ev.add_item(EvidenceItem(course_id="C001", source="remotive", title="Job", url="", signal_type="job"))
    # Give it 5 web results
    for _ in range(5):
        ev.add_item(EvidenceItem(course_id="C001", source="duckduckgo", title="Web", url="", signal_type="web"))
    
    signals = compute_signals(ev, arxiv_total=1000)
    assert signals.job_signal == 100.0
    assert signals.web_signal == 100.0
    assert signals.research_signal > 99.0

def test_confidence_calculation_fallback():
    ev = CourseEvidence(course_id="C001", title="Test", keywords=[])
    assert ev.confidence() == 0.15 # fallback when no sources successful
