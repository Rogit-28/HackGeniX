"""
Interview Session API endpoints.

Provides REST API for managing complete interview sessions.
"""
import logging
from typing import Optional, List

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status, Query, Depends

from src.core.auth import require_permission, require_session_access
from src.core.database import mongodb_client
from src.core.permissions import Permissions
from src.models.auth import AuthenticatedUser
from src.models.interview import (
    InterviewStatus,
    StartInterviewRequest,
    StartInterviewResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    InterviewProgressResponse,
    EndInterviewRequest,
    InterviewReportResponse,
)
from src.models.documents import ParsedResume, ParsedJobDescription
from src.services.interview_orchestrator import get_interview_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("/start", response_model=StartInterviewResponse)
async def start_interview(
    request: StartInterviewRequest,
    user: AuthenticatedUser = Depends(require_permission(Permissions.CREATE_SESSION)),
):
    """
    Start a new interview session.
    
    Creates an interview session with questions generated based on the
    candidate's resume and the job description.
    """
    orchestrator = get_interview_orchestrator()
    
    # Fetch resume from MongoDB
    try:
        resume_doc = await mongodb_client.resumes.find_one(
            {"_id": ObjectId(request.resume_id)}
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resume ID: {request.resume_id}",
        )
    
    if not resume_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Resume not found: {request.resume_id}",
        )
    
    if resume_doc.get("status") != "parsed" or not resume_doc.get("parsed_data"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume must be successfully parsed before starting an interview. Please re-upload.",
        )
    
    # Fetch job description from MongoDB
    try:
        jd_doc = await mongodb_client.job_descriptions.find_one(
            {"_id": ObjectId(request.job_description_id)}
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid job description ID: {request.job_description_id}",
        )
    
    if not jd_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job description not found: {request.job_description_id}",
        )
    
    if jd_doc.get("status") != "parsed" or not jd_doc.get("parsed_data"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job description must be successfully parsed before starting an interview. Please re-upload.",
        )
    
    # Reconstruct Pydantic models from stored data
    resume = ParsedResume(**resume_doc["parsed_data"])
    jd = ParsedJobDescription(**jd_doc["parsed_data"])
    
    try:
        session, response = await orchestrator.start_interview(
            resume=resume,
            jd=jd,
            resume_id=request.resume_id,
            jd_id=request.job_description_id,
            config=request.config,
        )
        
        logger.info(f"Interview started: session={session.id}, questions={len(session.questions)}")
        return response
        
    except Exception as e:
        logger.error(f"Failed to start interview: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start interview: {str(e)}",
        )


@router.post("/answer", response_model=SubmitAnswerResponse)
async def submit_answer(
    request: SubmitAnswerRequest,
    user: AuthenticatedUser = Depends(require_permission(Permissions.PARTICIPATE_SESSION)),
):
    """
    Submit an answer for the current question.
    
    Accepts text answers or audio (for voice mode).
    Returns evaluation and next question.
    """
    orchestrator = get_interview_orchestrator()
    
    try:
        response = await orchestrator.submit_answer(
            session_id=request.session_id,
            answer_text=request.answer_text,
            answer_audio_base64=request.answer_audio_base64,
        )
        
        logger.info(
            f"Answer submitted: session={request.session_id}, "
            f"score={response.evaluation.get('scores', {}).get('overall', 0) if response.evaluation else 0}"
        )
        return response
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to submit answer: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit answer: {str(e)}",
        )


@router.get("/{session_id}/progress", response_model=InterviewProgressResponse)
async def get_progress(
    session_id: str,
    user: AuthenticatedUser = Depends(require_session_access("session_id")),
):
    """Get current interview progress and state."""
    orchestrator = get_interview_orchestrator()
    
    try:
        return orchestrator.get_progress(session_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.get("/{session_id}", response_model=dict)
async def get_session(
    session_id: str,
    user: AuthenticatedUser = Depends(require_session_access("session_id")),
):
    """Get full interview session details."""
    orchestrator = get_interview_orchestrator()
    
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
    
    # model_dump() excludes @property fields, so add them manually
    data = session.model_dump()
    data["current_question"] = (
        session.current_question.model_dump() if session.current_question else None
    )
    data["duration_minutes"] = session.duration_minutes
    data["overall_score"] = session.overall_score
    data["total_questions"] = len(session.questions)
    return data


@router.post("/{session_id}/end", response_model=InterviewReportResponse)
async def end_interview(
    session_id: str,
    request: Optional[EndInterviewRequest] = None,
    user: AuthenticatedUser = Depends(require_session_access("session_id")),
):
    """
    End an interview and generate the final report.
    
    Can be called to end early or after all questions are answered.
    """
    orchestrator = get_interview_orchestrator()
    
    try:
        reason = request.reason if request else None
        return await orchestrator.end_interview(session_id, reason)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to end interview: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to end interview: {str(e)}",
        )


@router.get("/{session_id}/report", response_model=InterviewReportResponse)
async def get_report(
    session_id: str,
    user: AuthenticatedUser = Depends(require_permission(Permissions.VIEW_REPORTS)),
):
    """
    Get the interview report.
    
    Generates a comprehensive report with scores and recommendations.
    """
    orchestrator = get_interview_orchestrator()
    
    try:
        return await orchestrator.generate_report(session_id)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}",
        )


@router.post("/{session_id}/pause")
async def pause_interview(
    session_id: str,
    user: AuthenticatedUser = Depends(require_session_access("session_id")),
):
    """Pause an ongoing interview."""
    orchestrator = get_interview_orchestrator()
    
    try:
        session = orchestrator.pause_interview(session_id)
        return {
            "session_id": session_id,
            "status": session.status.value,
            "message": "Interview paused",
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post("/{session_id}/resume")
async def resume_interview(
    session_id: str,
    user: AuthenticatedUser = Depends(require_session_access("session_id")),
):
    """Resume a paused interview."""
    orchestrator = get_interview_orchestrator()
    
    try:
        session = orchestrator.resume_interview(session_id)
        return {
            "session_id": session_id,
            "status": session.status.value,
            "current_question": session.current_question,
            "message": "Interview resumed",
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.get("/", response_model=List[dict])
async def list_sessions(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    user: AuthenticatedUser = Depends(require_permission(Permissions.VIEW_SESSION)),
):
    """List interview sessions."""
    orchestrator = get_interview_orchestrator()
    
    status_filter = None
    if status:
        try:
            status_filter = InterviewStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status}",
            )
    
    sessions = orchestrator.list_sessions(status=status_filter, limit=limit)
    
    return [
        {
            "id": s.id,
            "candidate_name": s.candidate_name,
            "role_title": s.role_title,
            "status": s.status.value if hasattr(s.status, 'value') else s.status,
            "current_stage": s.current_stage.value if hasattr(s.current_stage, 'value') else s.current_stage,
            "questions_answered": len(s.answers),
            "total_questions": len(s.questions),
            "overall_score": s.overall_score,
            "duration_minutes": s.duration_minutes,
            "created_at": s.created_at.isoformat(),
        }
        for s in sessions
    ]


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user: AuthenticatedUser = Depends(require_permission(Permissions.DELETE_SESSION)),
):
    """Delete an interview session."""
    orchestrator = get_interview_orchestrator()
    
    if orchestrator.delete_session(session_id):
        return {"message": f"Session {session_id} deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

