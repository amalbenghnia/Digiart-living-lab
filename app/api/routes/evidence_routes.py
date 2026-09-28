from fastapi import APIRouter, HTTPException
from app.models.evidence import CourseEvidence, EVIDENCE_STORE

router = APIRouter(prefix="/market", tags=["market", "evidence"])

@router.get("/evidence/{course_id}", response_model=CourseEvidence)
def get_evidence(course_id: str):
    """Return all collected evidence and LLM analysis for a course."""
    evidence = EVIDENCE_STORE.get(course_id)
    if not evidence:
        raise HTTPException(
            status_code=404, 
            detail=f"No evidence collected yet for course {course_id}. Try refreshing market data."
        )
    return evidence
