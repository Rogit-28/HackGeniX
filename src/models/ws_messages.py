"""
WebSocket message types for real-time voice interview.

Defines the JSON message protocol used between the frontend JS WebSocket
client and the backend WebSocket handler.

Binary messages (audio) are sent raw — only JSON control/data messages
use these types.

Client -> Server (JSON):
    control         — start/stop recording, skip question, end interview
    text_answer     — fallback text answer (hybrid mode)
    audio_meta      — metadata about upcoming binary audio (mime type, etc.)

Server -> Client (JSON):
    connected       — handshake: session info + first question
    question        — new question text + metadata + timer
    tts_start       — TTS audio about to start streaming
    tts_end         — TTS audio finished
    listening       — server ready to receive audio (mic timer started)
    transcript      — partial or final transcription
    evaluating      — evaluation in progress
    evaluation      — scores, strengths, improvements, next question
    stage_change    — interview stage transition
    progress        — progress update
    interview_complete — interview finished
    error           — error message
    timer_warning   — answer time running low
    timer_expired   — answer time expired, auto-submitting

Server -> Client (Binary):
    Raw WAV audio bytes (TTS question audio chunks)

Client -> Server (Binary):
    Raw audio bytes from MediaRecorder (WebM/Opus or WAV)
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============== Client -> Server ==============


class ClientMessageType(str, Enum):
    """Types of messages the client can send (JSON)."""
    CONTROL = "control"
    TEXT_ANSWER = "text_answer"
    AUDIO_META = "audio_meta"


class ControlAction(str, Enum):
    """Control actions the client can request."""
    START_RECORDING = "start_recording"
    STOP_RECORDING = "stop_recording"
    SKIP_QUESTION = "skip_question"
    END_INTERVIEW = "end_interview"
    PAUSE = "pause"
    RESUME = "resume"


class ClientMessage(BaseModel):
    """Base model for all client JSON messages."""
    type: ClientMessageType


class ControlMessage(ClientMessage):
    """Client control message."""
    type: ClientMessageType = ClientMessageType.CONTROL
    action: ControlAction


class TextAnswerMessage(ClientMessage):
    """Fallback text answer (hybrid mode)."""
    type: ClientMessageType = ClientMessageType.TEXT_ANSWER
    text: str


class AudioMetaMessage(ClientMessage):
    """Metadata about audio stream starting."""
    type: ClientMessageType = ClientMessageType.AUDIO_META
    mime_type: str = "audio/webm;codecs=opus"
    sample_rate: Optional[int] = None


# ============== Server -> Client ==============


class ServerMessageType(str, Enum):
    """Types of messages the server can send (JSON)."""
    CONNECTED = "connected"
    QUESTION = "question"
    TTS_START = "tts_start"
    TTS_END = "tts_end"
    LISTENING = "listening"
    TRANSCRIPT = "transcript"
    EVALUATING = "evaluating"
    EVALUATION = "evaluation"
    STAGE_CHANGE = "stage_change"
    PROGRESS = "progress"
    INTERVIEW_COMPLETE = "interview_complete"
    ERROR = "error"
    TIMER_WARNING = "timer_warning"
    TIMER_EXPIRED = "timer_expired"


class ServerMessage(BaseModel):
    """Base model for all server JSON messages."""
    type: ServerMessageType


class ConnectedMessage(ServerMessage):
    """Handshake response after WebSocket connection."""
    type: ServerMessageType = ServerMessageType.CONNECTED
    session_id: str
    candidate_name: Optional[str] = None
    role_title: Optional[str] = None
    current_stage: str
    total_questions: int
    questions_answered: int
    # First question is sent separately as a QuestionMessage


class QuestionMessage(ServerMessage):
    """New question for the candidate."""
    type: ServerMessageType = ServerMessageType.QUESTION
    question_id: str
    question_text: str
    stage: str
    difficulty: str = "medium"
    question_number: int
    total_questions: int
    duration_seconds: int = 120  # time limit for answer
    category: Optional[str] = None
    purpose: Optional[str] = None
    has_tts: bool = True  # whether TTS will follow


class TTSStartMessage(ServerMessage):
    """TTS audio streaming is about to begin."""
    type: ServerMessageType = ServerMessageType.TTS_START
    question_id: str
    total_chunks: int = 1
    # Binary WAV chunks follow this message


class TTSEndMessage(ServerMessage):
    """TTS audio streaming finished."""
    type: ServerMessageType = ServerMessageType.TTS_END
    question_id: str
    duration_seconds: float = 0.0


class ListeningMessage(ServerMessage):
    """Server is ready to receive audio. Timer started."""
    type: ServerMessageType = ServerMessageType.LISTENING
    question_id: str
    duration_seconds: int  # how long the client has to answer
    auto_submit_on_expire: bool = True


class TranscriptMessage(ServerMessage):
    """Transcription result (partial or final)."""
    type: ServerMessageType = ServerMessageType.TRANSCRIPT
    text: str
    is_final: bool = False
    confidence: float = 0.0
    duration_seconds: float = 0.0


class EvaluatingMessage(ServerMessage):
    """Answer is being evaluated."""
    type: ServerMessageType = ServerMessageType.EVALUATING
    message: str = "Evaluating your answer..."


class EvaluationMessage(ServerMessage):
    """Answer evaluation results."""
    type: ServerMessageType = ServerMessageType.EVALUATION
    overall_score: float
    scores: Dict[str, float] = Field(default_factory=dict)
    strengths: List[str] = Field(default_factory=list)
    improvements: List[str] = Field(default_factory=list)
    recommendation: str = "acceptable"
    follow_up_question: Optional[str] = None
    # Progress info included for convenience
    questions_answered: int = 0
    total_questions: int = 0
    progress_percent: float = 0.0
    stage_changed: bool = False
    interview_complete: bool = False
    next_stage: Optional[str] = None


class StageChangeMessage(ServerMessage):
    """Interview stage transition."""
    type: ServerMessageType = ServerMessageType.STAGE_CHANGE
    from_stage: str
    to_stage: str
    message: str = ""


class ProgressMessage(ServerMessage):
    """Progress update."""
    type: ServerMessageType = ServerMessageType.PROGRESS
    questions_answered: int
    total_questions: int
    progress_percent: float
    current_stage: str
    overall_score: float = 0.0


class InterviewCompleteMessage(ServerMessage):
    """Interview finished."""
    type: ServerMessageType = ServerMessageType.INTERVIEW_COMPLETE
    session_id: str
    overall_score: float
    total_questions: int
    questions_answered: int
    duration_minutes: int
    message: str = "Interview complete!"


class ErrorMessage(ServerMessage):
    """Error message."""
    type: ServerMessageType = ServerMessageType.ERROR
    message: str
    recoverable: bool = True  # if false, WS will close


class TimerWarningMessage(ServerMessage):
    """Warning that answer time is running low."""
    type: ServerMessageType = ServerMessageType.TIMER_WARNING
    question_id: str
    seconds_remaining: int


class TimerExpiredMessage(ServerMessage):
    """Answer time expired, auto-submitting."""
    type: ServerMessageType = ServerMessageType.TIMER_EXPIRED
    question_id: str
    message: str = "Time expired. Submitting your answer..."
