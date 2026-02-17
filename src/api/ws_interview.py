"""
Real-time WebSocket endpoint for voice interviews.

Provides bidirectional audio streaming between the frontend and the
interview pipeline (STT -> Evaluate -> TTS).

Protocol:
    - Text (JSON) messages carry control signals and structured data.
    - Binary messages carry raw audio (client->server: mic, server->client: TTS).

Connection URL:
    ws://<host>/api/v1/interview/ws/<session_id>?token=<JWT>

Flow per question:
    1. Server sends ``question`` message with text + timer duration.
    2. Server streams TTS audio as binary chunks (bracketed by
       ``tts_start`` / ``tts_end``).
    3. Server sends ``listening`` — client opens mic for ``duration_seconds``.
    4. Client streams binary audio chunks until user stops or timer expires.
    5. Client sends ``{"type":"control","action":"stop_recording"}`` (or
       timer fires server-side).
    6. Server transcribes audio via Groq Whisper, sends ``transcript``.
    7. Server evaluates answer, sends ``evaluation``.
    8. Server moves to next question (goto 1) or sends
       ``interview_complete``.

Hybrid mode:
    Client may send ``{"type":"text_answer","text":"..."}`` instead of
    audio, in which case steps 3-6 are skipped and evaluation starts
    immediately.
"""
import asyncio
import io
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from src.core.auth import decode_token, get_auth_config
from src.core.config import get_settings
from src.core.permissions import Permissions, get_permissions_for_role
from src.models.auth import AuthenticatedUser, UserRole
from src.models.interview import (
    InterviewMode,
    InterviewQuestion,
    InterviewSession,
    InterviewStage,
    InterviewStatus,
    QuestionStatus,
    SubmitAnswerResponse,
)
from src.models.ws_messages import (
    ClientMessageType,
    ConnectedMessage,
    ControlAction,
    ErrorMessage,
    EvaluatingMessage,
    EvaluationMessage,
    InterviewCompleteMessage,
    ListeningMessage,
    ProgressMessage,
    QuestionMessage,
    ServerMessageType,
    StageChangeMessage,
    TimerExpiredMessage,
    TimerWarningMessage,
    TranscriptMessage,
    TTSEndMessage,
    TTSStartMessage,
)
from src.services.interview_orchestrator import get_interview_orchestrator
from src.services.streaming import StreamEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket Interview"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _send_json(ws: WebSocket, msg) -> bool:
    """Send a Pydantic model as JSON. Returns False if connection is closed."""
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_text(msg.model_dump_json())
            return True
    except Exception:
        pass
    return False


async def _send_error(ws: WebSocket, message: str, recoverable: bool = True) -> bool:
    return await _send_json(ws, ErrorMessage(message=message, recoverable=recoverable))


async def _authenticate_ws(ws: WebSocket, token: Optional[str], session_id: str) -> bool:
    """Validate JWT for WebSocket connections.

    Checks:
      1. Auth is enabled (bypasses if disabled).
      2. Token is present and valid (signature + expiry).
      3. User has PARTICIPATE_SESSION or CONDUCT_INTERVIEW permission (or ALL).
      4. User can access the specific session (admin/hiring_manager: any;
         candidate: only their scoped session; interviewer: via explicit grant).

    Returns True if auth passes. Sends an error and closes the socket on failure.
    """
    settings = get_settings()
    if not settings.auth_enabled:
        return True

    if not token:
        await ws.close(code=4001, reason="Missing token query parameter")
        return False

    try:
        token_payload = decode_token(token)
    except Exception as exc:
        await ws.close(code=4003, reason=f"Authentication failed: {exc}")
        return False

    # Resolve permissions
    if token_payload.permissions:
        effective_permissions = token_payload.permissions
    else:
        effective_permissions = get_permissions_for_role(token_payload.role)

    # Check permission: must have participate_session, conduct_interview, or all
    has_perm = (
        Permissions.ALL in effective_permissions
        or Permissions.PARTICIPATE_SESSION in effective_permissions
        or Permissions.CONDUCT_INTERVIEW in effective_permissions
    )
    if not has_perm:
        logger.warning(
            f"WS auth denied: user={token_payload.sub} role={token_payload.role.value} "
            f"lacks interview permission for session={session_id}"
        )
        await _send_error(ws, "You don't have permission to join interviews", recoverable=False)
        await ws.close(code=4003, reason="Insufficient permissions")
        return False

    # Build AuthenticatedUser to check session access
    user = AuthenticatedUser(
        user_id=token_payload.sub,
        role=token_payload.role,
        permissions=effective_permissions,
        session_id=token_payload.session_id,
        name=token_payload.name,
        email=token_payload.email,
        token_exp=token_payload.exp,
        token_iss=token_payload.iss,
    )

    if not user.can_access_session(session_id):
        logger.warning(
            f"WS auth denied: user={user.user_id} role={user.role.value} "
            f"cannot access session={session_id} (scoped to {user.session_id})"
        )
        await _send_error(ws, "You don't have access to this interview session", recoverable=False)
        await ws.close(code=4003, reason="Session access denied")
        return False

    return True


def _question_to_msg(
    question: InterviewQuestion,
    question_number: int,
    total_questions: int,
    follow_up_count: int = 0,
) -> QuestionMessage:
    """Convert an InterviewQuestion to a QuestionMessage.
    
    For follow-up sub-questions, generates a label like "Q3a", "Q3b" etc.
    """
    is_follow_up = question.parent_question_id is not None
    sub_label = None
    if is_follow_up and question.sub_question_number:
        # Convert sub_question_number to letter suffix: 1->a, 2->b, etc.
        suffix = chr(ord('a') + question.sub_question_number - 1)
        sub_label = f"Q{question_number}{suffix}"
    
    return QuestionMessage(
        question_id=question.id,
        question_text=question.question_text,
        stage=question.stage if isinstance(question.stage, str) else question.stage.value,
        difficulty=question.difficulty,
        question_number=question_number,
        total_questions=total_questions,
        duration_seconds=question.duration_seconds,
        category=question.category,
        purpose=question.purpose,
        has_tts=True,
        is_follow_up=is_follow_up,
        parent_question_id=question.parent_question_id,
        sub_question_label=sub_label,
        follow_up_count=follow_up_count,
    )


# ---------------------------------------------------------------------------
# TTS pipelining
# ---------------------------------------------------------------------------

async def _stream_tts(ws: WebSocket, question: InterviewQuestion, voice: Optional[str] = None):
    """Synthesize question audio via Groq Orpheus and stream WAV chunks.

    Chunks text into <=200-char pieces, synthesizes each, and sends
    binary WAV data to the client for seamless playback.
    """
    from src.providers.tts import get_tts_provider_async
    from src.providers.tts.groq_tts_provider import GroqTTSProvider

    try:
        tts = await get_tts_provider_async()

        # Chunk the question text
        text = question.question_text
        if hasattr(tts, '_chunk_text'):
            chunks = tts._chunk_text(text, 200)
        else:
            chunks = GroqTTSProvider._chunk_text(text, 200)

        await _send_json(ws, TTSStartMessage(
            question_id=question.id,
            total_chunks=len(chunks),
        ))

        total_duration = 0.0
        for chunk_text in chunks:
            result = await tts.synthesize(text=chunk_text, voice_id=voice)
            total_duration += result.duration_seconds
            # Send raw WAV bytes
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_bytes(result.audio_data)

        await _send_json(ws, TTSEndMessage(
            question_id=question.id,
            duration_seconds=total_duration,
        ))

    except Exception as exc:
        logger.error(f"TTS streaming failed: {exc}")
        await _send_error(ws, f"TTS failed: {exc}")


# ---------------------------------------------------------------------------
# STT
# ---------------------------------------------------------------------------

async def _transcribe_audio(
    audio_buffer: bytes,
    mime_type: str = "audio/webm",
    context: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Transcribe accumulated audio via Groq Whisper.

    Returns dict with text, confidence, duration_seconds.
    """
    from src.providers.stt import get_stt_provider_async

    stt = await get_stt_provider_async()

    logger.info(
        "Transcribing audio: %d bytes, mime=%s, has_context=%s",
        len(audio_buffer), mime_type, bool(context),
    )

    if context:
        result = await stt.transcribe_with_interview_context(
            audio_data=audio_buffer,
            technical_terms=context,
            content_type=mime_type,
        )
    else:
        result = await stt.transcribe(
            audio_data=audio_buffer,
            content_type=mime_type,
        )

    return {
        "text": result.text,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
    }


# ---------------------------------------------------------------------------
# Answer evaluation (reuses orchestrator's submit_answer_stream)
# ---------------------------------------------------------------------------

async def _evaluate_and_advance(
    ws: WebSocket,
    session_id: str,
    answer_text: str,
) -> Optional[SubmitAnswerResponse]:
    """Submit answer through the orchestrator and relay progress to the WS.

    Returns the SubmitAnswerResponse, or None on failure.
    """
    orchestrator = get_interview_orchestrator()

    await _send_json(ws, EvaluatingMessage(message="Evaluating your answer..."))

    response: Optional[SubmitAnswerResponse] = None

    try:
        async for item in orchestrator.submit_answer_stream(
            session_id=session_id,
            answer_text=answer_text,
        ):
            if isinstance(item, StreamEvent):
                # Forward status/progress events as simple progress messages
                await _send_json(ws, ProgressMessage(
                    questions_answered=0,
                    total_questions=0,
                    progress_percent=0,
                    current_stage=item.stage,
                    overall_score=0,
                ))
            elif isinstance(item, SubmitAnswerResponse):
                response = item
    except Exception as exc:
        logger.error(f"Evaluation failed: {exc}")
        await _send_error(ws, f"Evaluation failed: {exc}")
        return None

    return response


# ---------------------------------------------------------------------------
# Main WebSocket handler
# ---------------------------------------------------------------------------

@router.websocket("/api/v1/interview/ws/{session_id}")
async def interview_websocket(
    ws: WebSocket,
    session_id: str,
    token: Optional[str] = Query(None),
):
    """
    Real-time voice interview WebSocket endpoint.

    Connect with: ``ws://<host>/api/v1/interview/ws/<session_id>?token=<JWT>``
    """
    # --- Accept connection ---
    await ws.accept()

    # --- Authenticate ---
    if not await _authenticate_ws(ws, token, session_id):
        return

    # --- Load session ---
    orchestrator = get_interview_orchestrator()
    session = await orchestrator.get_session(session_id)

    if not session:
        await _send_error(ws, f"Session not found: {session_id}", recoverable=False)
        await ws.close(code=4004, reason="Session not found")
        return

    status_val = session.status if isinstance(session.status, str) else session.status.value
    if status_val != "in_progress":
        await _send_error(ws, f"Session is not in progress (status={status_val})", recoverable=False)
        await ws.close(code=4005, reason="Session not in progress")
        return

    current_question = session.current_question
    if not current_question:
        await _send_error(ws, "No pending questions in session", recoverable=False)
        await ws.close(code=4006, reason="No pending questions")
        return

    # --- Send connected handshake ---
    # Use base question counts (Phase 7: exclude follow-up sub-questions)
    base_total = sum(1 for q in session.questions if q.parent_question_id is None)
    base_answered = sum(
        1 for q in session.questions
        if q.parent_question_id is None
        and (q.status if isinstance(q.status, str) else q.status.value) == "answered"
    )
    await _send_json(ws, ConnectedMessage(
        session_id=session_id,
        candidate_name=session.candidate_name,
        role_title=session.role_title,
        current_stage=session.current_stage if isinstance(session.current_stage, str) else session.current_stage.value,
        total_questions=base_total,
        questions_answered=base_answered,
    ))

    logger.info(
        f"WS connected: session={session_id}, "
        f"candidate={session.candidate_name}, "
        f"question={base_answered+1}/{base_total}"
    )

    # --- State ---
    audio_buffer = bytearray()
    audio_mime_type = "audio/webm"
    is_recording = False
    answer_timer_task: Optional[asyncio.Task] = None
    current_q = current_question
    tts_voice = session.config.tts_voice

    async def _cancel_timer():
        nonlocal answer_timer_task
        if answer_timer_task and not answer_timer_task.done():
            answer_timer_task.cancel()
            try:
                await answer_timer_task
            except asyncio.CancelledError:
                pass
        answer_timer_task = None

    async def _send_question_and_listen(question: InterviewQuestion):
        """Send question, stream TTS, start listening timer."""
        nonlocal current_q, is_recording, audio_buffer, answer_timer_task

        current_q = question
        
        # Phase 7: Compute base question number (excluding follow-ups)
        # Reload session to get latest state
        s = await orchestrator.get_session(session_id)
        base_answered_count = sum(
            1 for q in s.questions
            if q.parent_question_id is None
            and (q.status if isinstance(q.status, str) else q.status.value) == "answered"
        )
        base_total_count = sum(1 for q in s.questions if q.parent_question_id is None)
        
        # For follow-ups, question_number stays as the parent's base number
        if question.parent_question_id is not None:
            # Find the base question number of the parent
            base_num = 0
            for q in s.questions:
                if q.parent_question_id is None:
                    base_num += 1
                if q.id == question.parent_question_id:
                    break
            question_number = base_num
        else:
            question_number = base_answered_count + 1

        # Send question metadata
        await _send_json(ws, _question_to_msg(
            question, question_number, base_total_count,
            follow_up_count=s.follow_up_count,
        ))

        # Stream TTS audio
        await _stream_tts(ws, question, voice=tts_voice)

        # Tell client to open mic
        is_recording = True
        audio_buffer = bytearray()
        await _send_json(ws, ListeningMessage(
            question_id=question.id,
            duration_seconds=question.duration_seconds,
            auto_submit_on_expire=True,
        ))

        # Start server-side answer timer
        answer_timer_task = asyncio.create_task(
            _answer_timer(question.id, question.duration_seconds)
        )

    async def _answer_timer(question_id: str, duration: int):
        """Server-side timer: warn at 80%, auto-submit at 100%."""
        try:
            warning_at = int(duration * 0.8)
            remaining_after_warning = duration - warning_at

            # Wait until 80% elapsed
            await asyncio.sleep(warning_at)
            await _send_json(ws, TimerWarningMessage(
                question_id=question_id,
                seconds_remaining=remaining_after_warning,
            ))

            # Wait remaining 20%
            await asyncio.sleep(remaining_after_warning)

            # Timer expired — auto-submit whatever we have
            await _send_json(ws, TimerExpiredMessage(
                question_id=question_id,
            ))
            await _process_answer(from_timer=True)

        except asyncio.CancelledError:
            pass  # Timer cancelled because user stopped recording

    async def _process_answer(from_timer: bool = False):
        """Transcribe audio (if any), evaluate, advance to next question."""
        nonlocal is_recording, current_q

        is_recording = False
        await _cancel_timer()

        answer_text = ""

        # Transcribe if we have audio
        if len(audio_buffer) > 100:  # skip tiny/empty buffers
            try:
                context = session.config.focus_skills or []
                result = await _transcribe_audio(
                    bytes(audio_buffer), audio_mime_type, context or None,
                )
                answer_text = result["text"]

                await _send_json(ws, TranscriptMessage(
                    text=answer_text,
                    is_final=True,
                    confidence=result["confidence"],
                    duration_seconds=result["duration_seconds"],
                ))
            except Exception as exc:
                logger.error(f"Transcription failed: {exc}")
                await _send_error(ws, f"Transcription failed: {exc}")
                if from_timer:
                    # Timer already expired — can't re-open listening,
                    # auto-submit with fallback text so interview advances
                    answer_text = "(No answer provided - timer expired)"
                else:
                    # Manual stop — re-open mic so user can try again or type
                    is_recording = True
                    audio_buffer.clear()
                    await _send_json(ws, ListeningMessage(
                        question_id=current_q.id,
                        duration_seconds=current_q.duration_seconds,
                        auto_submit_on_expire=True,
                    ))
                    return

        if not answer_text.strip():
            if from_timer:
                # Timer expired with no speech — auto-skip with fallback text
                # so the interview advances (will score low but won't get stuck)
                answer_text = "(No answer provided - timer expired)"
            else:
                await _send_error(ws, "No speech detected. Please try again or type your answer.")
                # Re-open listening
                is_recording = True
                audio_buffer.clear()
                await _send_json(ws, ListeningMessage(
                    question_id=current_q.id,
                    duration_seconds=current_q.duration_seconds,
                    auto_submit_on_expire=True,
                ))
                return

        # Evaluate answer
        response = await _evaluate_and_advance(ws, session_id, answer_text)
        if not response:
            return

        # Send evaluation results
        eval_data = response.evaluation or {}
        scores = eval_data.get("scores", {})

        # Reload session to get latest state (orchestrator mutated it)
        session_refreshed = await orchestrator.get_session(session_id)
        latest_answer = session_refreshed.answers[-1] if session_refreshed and session_refreshed.answers else None

        await _send_json(ws, EvaluationMessage(
            overall_score=scores.get("overall", 0),
            scores=scores,
            strengths=latest_answer.strengths if latest_answer else [],
            improvements=latest_answer.improvements if latest_answer else [],
            recommendation=latest_answer.recommendation if latest_answer else "acceptable",
            follow_up_question=latest_answer.follow_up_question if latest_answer else None,
            questions_answered=response.questions_answered,
            total_questions=response.total_questions,
            progress_percent=response.progress_percent,
            stage_changed=response.stage_changed,
            interview_complete=response.interview_complete,
            next_stage=response.current_stage if response.stage_changed else None,
            follow_up_count=session_refreshed.follow_up_count if session_refreshed else 0,
        ))

        # Stage change notification
        if response.stage_changed:
            old_stage = current_q.stage if isinstance(current_q.stage, str) else current_q.stage.value
            await _send_json(ws, StageChangeMessage(
                from_stage=old_stage,
                to_stage=response.current_stage,
                message=f"Moving to {response.current_stage.replace('_', ' ')} stage",
            ))

        # Check if interview is complete
        if response.interview_complete:
            s = session_refreshed or session
            await _send_json(ws, InterviewCompleteMessage(
                session_id=session_id,
                overall_score=s.overall_score,
                total_questions=len(s.questions),
                questions_answered=len(s.answers),
                duration_minutes=s.duration_minutes,
            ))
            await ws.close(code=1000, reason="Interview complete")
            return

        # Send next question
        if response.next_question:
            await _send_question_and_listen(response.next_question)

    # --- Send first question and start the interview ---
    try:
        await _send_question_and_listen(current_q)
    except Exception as exc:
        logger.error(f"Failed to send first question: {exc}")
        await _send_error(ws, f"Failed to start: {exc}", recoverable=False)
        await ws.close(code=1011, reason="Internal error")
        return

    # --- Main receive loop ---
    try:
        while True:
            message = await ws.receive()
            msg_type = message.get("type")

            if msg_type == "websocket.disconnect":
                break

            # --- Binary: audio data ---
            if msg_type == "websocket.receive" and "bytes" in message and message["bytes"]:
                if is_recording:
                    audio_buffer.extend(message["bytes"])
                continue

            # --- Text: JSON control messages ---
            if msg_type == "websocket.receive" and "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    await _send_error(ws, "Invalid JSON")
                    continue

                msg_kind = data.get("type", "")

                # --- Audio metadata ---
                if msg_kind == ClientMessageType.AUDIO_META.value:
                    audio_mime_type = data.get("mime_type", "audio/webm")
                    continue

                # --- Control messages ---
                if msg_kind == ClientMessageType.CONTROL.value:
                    action = data.get("action", "")

                    if action == ControlAction.START_RECORDING.value:
                        is_recording = True
                        audio_buffer = bytearray()
                        continue

                    if action == ControlAction.STOP_RECORDING.value:
                        # Grace period: keep accepting trailing audio chunks
                        # for up to 500ms.  The browser's MediaRecorder fires
                        # ondataavailable every 250ms, so the final chunk may
                        # arrive *after* the JSON stop message.
                        is_recording = True  # keep gate open for trailing bytes
                        buf_before = len(audio_buffer)
                        await asyncio.sleep(0.5)
                        is_recording = False
                        logger.info(
                            "stop_recording: buffer %d -> %d bytes (+%d trailing)",
                            buf_before, len(audio_buffer),
                            len(audio_buffer) - buf_before,
                        )
                        await _process_answer()
                        continue

                    if action == ControlAction.SKIP_QUESTION.value:
                        await _cancel_timer()
                        is_recording = False
                        # Submit empty answer (will be scored low)
                        response = await _evaluate_and_advance(
                            ws, session_id, "(Question skipped by candidate)",
                        )
                        if not response:
                            continue

                        # Send evaluation results for skipped question
                        eval_data = response.evaluation or {}
                        eval_scores = eval_data.get("scores", {})
                        session_refreshed = await orchestrator.get_session(session_id)
                        latest_answer = session_refreshed.answers[-1] if session_refreshed and session_refreshed.answers else None

                        await _send_json(ws, EvaluationMessage(
                            overall_score=eval_scores.get("overall", 0),
                            scores=eval_scores,
                            strengths=latest_answer.strengths if latest_answer else [],
                            improvements=latest_answer.improvements if latest_answer else [],
                            recommendation=latest_answer.recommendation if latest_answer else "acceptable",
                            follow_up_question=latest_answer.follow_up_question if latest_answer else None,
                            questions_answered=response.questions_answered,
                            total_questions=response.total_questions,
                            progress_percent=response.progress_percent,
                            stage_changed=response.stage_changed,
                            interview_complete=response.interview_complete,
                            next_stage=response.current_stage if response.stage_changed else None,
                            follow_up_count=session_refreshed.follow_up_count if session_refreshed else 0,
                        ))

                        if response.stage_changed:
                            old_stage = current_q.stage if isinstance(current_q.stage, str) else current_q.stage.value
                            await _send_json(ws, StageChangeMessage(
                                from_stage=old_stage,
                                to_stage=response.current_stage,
                                message=f"Moving to {response.current_stage.replace('_', ' ')} stage",
                            ))

                        if response.interview_complete:
                            s = session_refreshed or session
                            await _send_json(ws, InterviewCompleteMessage(
                                session_id=session_id,
                                overall_score=s.overall_score if s else 0,
                                total_questions=response.total_questions,
                                questions_answered=response.questions_answered,
                                duration_minutes=s.duration_minutes if s else 0,
                            ))
                            await ws.close(code=1000, reason="Interview complete")
                            return

                        if response.next_question:
                            await _send_question_and_listen(response.next_question)
                        continue

                    if action == ControlAction.END_INTERVIEW.value:
                        await _cancel_timer()
                        is_recording = False
                        try:
                            await orchestrator.end_interview(session_id, reason="Ended by candidate via WebSocket")
                        except Exception:
                            pass
                        s = await orchestrator.get_session(session_id)
                        await _send_json(ws, InterviewCompleteMessage(
                            session_id=session_id,
                            overall_score=s.overall_score if s else 0,
                            total_questions=len(s.questions) if s else 0,
                            questions_answered=len(s.answers) if s else 0,
                            duration_minutes=s.duration_minutes if s else 0,
                            message="Interview ended early by candidate.",
                        ))
                        await ws.close(code=1000, reason="Interview ended by candidate")
                        return

                    if action == ControlAction.PAUSE.value:
                        await _cancel_timer()
                        is_recording = False
                        await orchestrator.pause_interview(session_id)
                        await _send_json(ws, ProgressMessage(
                            questions_answered=len(session.answers),
                            total_questions=len(session.questions),
                            progress_percent=0,
                            current_stage=session.current_stage if isinstance(session.current_stage, str) else session.current_stage.value,
                        ))
                        continue

                    if action == ControlAction.RESUME.value:
                        await orchestrator.resume_interview(session_id)
                        if current_q:
                            await _send_question_and_listen(current_q)
                        continue

                # --- Text answer (hybrid mode) ---
                if msg_kind == ClientMessageType.TEXT_ANSWER.value:
                    await _cancel_timer()
                    is_recording = False
                    text = data.get("text", "").strip()
                    if not text:
                        await _send_error(ws, "Empty text answer")
                        continue

                    # Send transcript for display
                    await _send_json(ws, TranscriptMessage(
                        text=text,
                        is_final=True,
                        confidence=1.0,
                    ))

                    response = await _evaluate_and_advance(ws, session_id, text)
                    if not response:
                        continue

                    # Send evaluation
                    eval_data = response.evaluation or {}
                    eval_scores = eval_data.get("scores", {})
                    session_refreshed = await orchestrator.get_session(session_id)
                    latest_answer = session_refreshed.answers[-1] if session_refreshed and session_refreshed.answers else None

                    await _send_json(ws, EvaluationMessage(
                        overall_score=eval_scores.get("overall", 0),
                        scores=eval_scores,
                        strengths=latest_answer.strengths if latest_answer else [],
                        improvements=latest_answer.improvements if latest_answer else [],
                        recommendation=latest_answer.recommendation if latest_answer else "acceptable",
                        follow_up_question=latest_answer.follow_up_question if latest_answer else None,
                        questions_answered=response.questions_answered,
                        total_questions=response.total_questions,
                        progress_percent=response.progress_percent,
                        stage_changed=response.stage_changed,
                        interview_complete=response.interview_complete,
                        next_stage=response.current_stage if response.stage_changed else None,
                        follow_up_count=session_refreshed.follow_up_count if session_refreshed else 0,
                    ))

                    if response.stage_changed:
                        old_stage = current_q.stage if isinstance(current_q.stage, str) else current_q.stage.value
                        await _send_json(ws, StageChangeMessage(
                            from_stage=old_stage,
                            to_stage=response.current_stage,
                            message=f"Moving to {response.current_stage.replace('_', ' ')} stage",
                        ))

                    if response.interview_complete:
                        s = session_refreshed or session
                        await _send_json(ws, InterviewCompleteMessage(
                            session_id=session_id,
                            overall_score=s.overall_score,
                            total_questions=len(s.questions),
                            questions_answered=len(s.answers),
                            duration_minutes=s.duration_minutes,
                        ))
                        await ws.close(code=1000, reason="Interview complete")
                        return

                    if response.next_question:
                        await _send_question_and_listen(response.next_question)
                    continue

    except WebSocketDisconnect:
        logger.info(f"WS disconnected: session={session_id}")
    except Exception as exc:
        logger.error(f"WS error: session={session_id}, error={exc}")
        try:
            await _send_error(ws, f"Internal error: {exc}", recoverable=False)
            await ws.close(code=1011, reason="Internal error")
        except Exception:
            pass
    finally:
        await _cancel_timer()
        logger.info(f"WS closed: session={session_id}")
