"""
Interview Session API endpoints.

Provides REST API for managing complete interview sessions.
"""
import logging
from typing import Optional, List

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status, Query, Depends
from sse_starlette.sse import EventSourceResponse

from src.core.auth import require_permission, require_session_access
from src.core.database import mongodb_client
from src.core.permissions import Permissions
from src.models.auth import AuthenticatedUser
from src.models.interview import (
    InterviewStatus,
    InterviewSession,
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
from src.services.streaming import StreamEvent, error_event, done_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("/start")
async def start_interview(
    request: StartInterviewRequest,
    user: AuthenticatedUser = Depends(require_permission(Permissions.CREATE_SESSION)),
):
    """
    Start a new interview session (SSE streaming).
    
    Returns an SSE stream with real-time progress events as the interview
    is being set up (match analysis, question generation per stage).
    
    The interview becomes playable as soon as screening questions are ready
    (~5-8s) rather than waiting for all stages (~30s+).
    
    Event flow:
        status(session_created) → session ID available
        status/progress(matching) → match analysis progress
        result(match_complete) → match scores
        status(generating_screening) → screening gen starting
        result(questions_ready) → screening ready, interview_playable=true
        status(generating_technical) → ...
        result(questions_ready) → technical ready
        ... (behavioral, system_design, wrap_up)
        result(interview_ready) → all stages complete, full session data
        done → stream ends
    """
    orchestrator = get_interview_orchestrator()
    
    # --- Validation upfront (before entering SSE stream) ---
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
    
    # --- SSE stream ---
    async def event_generator():
        try:
            async for item in orchestrator.start_interview_stream(
                resume=resume,
                jd=jd,
                resume_id=request.resume_id,
                jd_id=request.job_description_id,
                config=request.config,
            ):
                if isinstance(item, StreamEvent):
                    yield item.to_sse()
                elif isinstance(item, InterviewSession):
                    # Final session object — we already sent interview_ready event
                    logger.info(
                        f"Interview started: session={item.id}, "
                        f"questions={len(item.questions)}"
                    )
                    # Stream is done
                    
        except Exception as e:
            logger.error(f"Failed to start interview: {e}")
            yield error_event("interview_start", f"Failed to start interview: {e}").to_sse()
            yield done_event("Stream ended due to error").to_sse()
    
    return EventSourceResponse(event_generator())


@router.post("/answer")
async def submit_answer(
    request: SubmitAnswerRequest,
    user: AuthenticatedUser = Depends(require_permission(Permissions.PARTICIPATE_SESSION)),
):
    """
    Submit an answer for the current question (SSE streaming).
    
    Returns an SSE stream with real-time progress as the answer is
    transcribed (voice mode), evaluated, validated, and scored.
    
    Event flow:
        status(transcribing)     -> audio transcription (voice mode only)
        progress(transcribing)   -> transcription complete
        status(evaluating)       -> LLM evaluation starting
        progress(evaluating)     -> scores available
        status(validating)       -> hallucination check
        progress(validating)     -> validation complete
        status(updating)         -> session state update
        result(answer_evaluated) -> complete evaluation + next question
        done                     -> stream ends
    """
    orchestrator = get_interview_orchestrator()
    
    # Validate session exists and is in progress before entering SSE stream
    session = await orchestrator.get_session(request.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {request.session_id}",
        )
    
    if session.status.value != "in_progress" if hasattr(session.status, 'value') else session.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is not in progress",
        )
    
    if not session.current_question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending questions in session",
        )
    
    if not request.answer_text and not request.answer_audio_base64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No answer provided (text or audio required)",
        )
    
    async def event_generator():
        try:
            async for item in orchestrator.submit_answer_stream(
                session_id=request.session_id,
                answer_text=request.answer_text,
                answer_audio_base64=request.answer_audio_base64,
            ):
                if isinstance(item, StreamEvent):
                    yield item.to_sse()
                elif isinstance(item, SubmitAnswerResponse):
                    logger.info(
                        f"Answer submitted: session={request.session_id}, "
                        f"score={item.evaluation.get('scores', {}).get('overall', 0) if item.evaluation else 0}"
                    )
                    
        except ValueError as e:
            yield error_event("answer_submission", str(e)).to_sse()
            yield done_event("Stream ended due to error").to_sse()
        except Exception as e:
            logger.error(f"Failed to submit answer: {e}")
            yield error_event("answer_submission", f"Failed to submit answer: {e}").to_sse()
            yield done_event("Stream ended due to error").to_sse()
    
    return EventSourceResponse(event_generator())


@router.get("/{session_id}/progress", response_model=InterviewProgressResponse)
async def get_progress(
    session_id: str,
    user: AuthenticatedUser = Depends(require_session_access("session_id")),
):
    """Get current interview progress and state."""
    orchestrator = get_interview_orchestrator()
    
    try:
        return await orchestrator.get_progress(session_id)
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
    
    session = await orchestrator.get_session(session_id)
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
        session = await orchestrator.pause_interview(session_id)
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
        session = await orchestrator.resume_interview(session_id)
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
    session_status: Optional[str] = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    user: AuthenticatedUser = Depends(require_permission(Permissions.VIEW_SESSION)),
):
    """List interview sessions."""
    orchestrator = get_interview_orchestrator()
    
    status_filter = None
    if session_status:
        try:
            status_filter = InterviewStatus(session_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {session_status}",
            )
    
    sessions = await orchestrator.list_sessions(status=status_filter, limit=limit)
    
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


@router.get("/{session_id}/augmentation-log", response_model=dict)
async def get_augmentation_log(
    session_id: str,
    user: AuthenticatedUser = Depends(require_session_access("session_id")),
):
    """
    Get the question augmentation log for a session.

    Shows which questions were augmented (original vs modified text),
    which were follow-ups, and the candidate context profile that
    drove augmentation decisions.  Intended for hiring managers /
    admins to inspect how the adaptive pipeline shaped the interview.
    """
    orchestrator = get_interview_orchestrator()

    session = await orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    # Build answer lookup: question_id -> AnswerRecord
    answer_map = {a.question_id: a for a in session.answers}

    # Track base question numbering (exclude follow-ups)
    base_number = 0
    questions_out = []
    augmented_count = 0

    for q in session.questions:
        is_follow_up = q.parent_question_id is not None
        if not is_follow_up:
            base_number += 1

        was_augmented = q.source == "augmented"
        if was_augmented:
            augmented_count += 1

        # Build sub-question label for follow-ups
        sub_label = None
        if is_follow_up and q.sub_question_number:
            suffix = chr(ord("a") + q.sub_question_number - 1)
            sub_label = f"Q{base_number}{suffix}"

        # Match answer if question was answered
        answer = answer_map.get(q.id)

        questions_out.append({
            "question_id": q.id,
            "question_number": base_number,
            "stage": q.stage if isinstance(q.stage, str) else q.stage.value,
            "source": q.source,
            "original_question_text": q.original_question_text,
            "augmented_question_text": q.question_text,
            "was_augmented": was_augmented,
            "is_follow_up": is_follow_up,
            "parent_question_id": q.parent_question_id,
            "sub_question_label": sub_label,
            "status": q.status if isinstance(q.status, str) else q.status.value,
            "answer_text": answer.answer_text if answer else None,
            "answer_score": answer.scores.get("overall", 0) if answer else None,
        })

    # Extract candidate context (strip qa_history to keep response slim)
    ctx = session.candidate_context or {}
    ctx_summary = {
        "demonstrated_skills": ctx.get("demonstrated_skills", []),
        "weak_areas": ctx.get("weak_areas", []),
        "standout_points": ctx.get("standout_points", []),
        "follow_up_hooks": ctx.get("follow_up_hooks", []),
        "cross_stage_connections": ctx.get("cross_stage_connections", []),
        "confidence_assessment": ctx.get("confidence_assessment", "unknown"),
        "suggested_focus": ctx.get("suggested_focus", ""),
    }

    return {
        "session_id": session.id,
        "enable_question_augmentation": session.config.enable_question_augmentation,
        "total_questions": len(session.questions),
        "augmented_count": augmented_count,
        "follow_up_count": session.follow_up_count,
        "questions": questions_out,
        "candidate_context": ctx_summary,
    }


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user: AuthenticatedUser = Depends(require_permission(Permissions.DELETE_SESSION)),
):
    """Delete an interview session."""
    orchestrator = get_interview_orchestrator()
    
    if await orchestrator.delete_session(session_id):
        return {"message": f"Session {session_id} deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

