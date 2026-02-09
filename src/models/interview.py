"""
Pydantic models for interview sessions.
"""
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class InterviewStatus(str, Enum):
    """Status of an interview session."""
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class InterviewStage(str, Enum):
    """Interview stages in order."""
    SCREENING = "screening"
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    SYSTEM_DESIGN = "system_design"
    WRAP_UP = "wrap_up"


class InterviewMode(str, Enum):
    """Mode of interview interaction."""
    TEXT = "text"
    VOICE = "voice"
    HYBRID = "hybrid"


class QuestionStatus(str, Enum):
    """Status of a question in the interview."""
    PENDING = "pending"
    ASKED = "asked"
    ANSWERED = "answered"
    SKIPPED = "skipped"


class AnswerRecord(BaseModel):
    """Record of a candidate's answer to a question."""
    question_id: str
    question_text: str
    stage: InterviewStage
    answer_text: str
    answer_audio_path: Optional[str] = None
    
    # Evaluation results
    scores: Dict[str, float] = Field(default_factory=dict)
    strengths: List[str] = Field(default_factory=list)
    improvements: List[str] = Field(default_factory=list)
    follow_up_question: Optional[str] = None
    recommendation: str = "acceptable"
    
    # Timing
    asked_at: datetime = Field(default_factory=datetime.utcnow)
    answered_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    
    class Config:
        use_enum_values = True


class InterviewQuestion(BaseModel):
    """A question in the interview queue."""
    id: str
    question_text: str
    stage: InterviewStage
    difficulty: str = "medium"
    category: Optional[str] = None
    purpose: str = ""
    expected_answer_points: List[str] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)
    duration_seconds: int = 120
    competency: Optional[str] = None  # For behavioral
    status: QuestionStatus = QuestionStatus.PENDING
    
    # Phase 6.5: Question source tracking
    source: str = "generated"  # bank, bank_rephrased, bank_personalized, generated
    
    # Audio for voice mode
    audio_path: Optional[str] = None
    
    class Config:
        use_enum_values = True


class StageProgress(BaseModel):
    """Progress tracking for an interview stage."""
    stage: InterviewStage
    total_questions: int = 0
    answered_questions: int = 0
    average_score: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    @property
    def is_complete(self) -> bool:
        return self.answered_questions >= self.total_questions
    
    @property
    def progress_percent(self) -> float:
        if self.total_questions == 0:
            return 0.0
        return (self.answered_questions / self.total_questions) * 100
    
    class Config:
        use_enum_values = True


class InterviewConfig(BaseModel):
    """Configuration for an interview session."""
    mode: InterviewMode = InterviewMode.TEXT
    
    # Question counts per stage
    screening_questions: int = 3
    technical_questions: int = 5
    behavioral_questions: int = 3
    system_design_questions: int = 1
    
    # Adaptive settings
    adaptive_difficulty: bool = True
    enable_follow_ups: bool = True
    max_follow_ups_per_question: int = 2
    
    # Time limits (in seconds, 0 = no limit)
    max_duration_seconds: int = 3600  # 1 hour default
    question_timeout_seconds: int = 300  # 5 min per question
    
    # Voice settings
    tts_voice: Optional[str] = None
    stt_model: str = "base"
    
    # Focus areas (optional, for customization)
    focus_skills: List[str] = Field(default_factory=list)
    exclude_topics: List[str] = Field(default_factory=list)
    
    # Question Bank settings (Phase 6.5)
    use_question_bank: bool = True                          # Enable hybrid question generation
    enabled_domains: Optional[List[str]] = None             # Admin-specified domains (None = auto-detect)
    auto_detect_domains: bool = True                        # Auto-detect domains from JD
    bank_question_ratio: float = Field(default=0.7, ge=0.0, le=1.0)  # 70% from bank
    allow_rephrasing: bool = True                           # LLM can rephrase bank questions
    allow_personalization: bool = True                      # LLM can add resume context
    
    class Config:
        use_enum_values = True


class InterviewSession(BaseModel):
    """Complete interview session state."""
    id: str
    
    # References
    resume_id: str
    job_description_id: str
    candidate_name: Optional[str] = None
    role_title: Optional[str] = None
    
    # Configuration
    config: InterviewConfig = Field(default_factory=InterviewConfig)
    
    # Status
    status: InterviewStatus = InterviewStatus.CREATED
    current_stage: InterviewStage = InterviewStage.SCREENING
    current_question_index: int = 0
    
    # Questions and answers
    questions: List[InterviewQuestion] = Field(default_factory=list)
    answers: List[AnswerRecord] = Field(default_factory=list)
    
    # Stage progress
    stage_progress: Dict[str, StageProgress] = Field(default_factory=dict)
    
    # Performance tracking
    current_difficulty: str = "medium"
    performance_trend: str = "stable"  # improving, declining, stable
    strong_areas: List[str] = Field(default_factory=list)
    weak_areas: List[str] = Field(default_factory=list)
    
    # Timing
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_activity_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Error tracking
    error_message: Optional[str] = None
    
    class Config:
        populate_by_name = True
        use_enum_values = True
    
    @property
    def duration_minutes(self) -> int:
        """Get total interview duration in minutes."""
        if not self.started_at:
            return 0
        end_time = self.completed_at or datetime.utcnow()
        return int((end_time - self.started_at).total_seconds() / 60)
    
    @property
    def overall_score(self) -> float:
        """Calculate overall average score."""
        if not self.answers:
            return 0.0
        scores = [a.scores.get("overall", 0) for a in self.answers if a.scores]
        return sum(scores) / len(scores) if scores else 0.0
    
    @property
    def current_question(self) -> Optional[InterviewQuestion]:
        """Get the current question to ask."""
        pending = [q for q in self.questions if q.status == QuestionStatus.PENDING.value]
        return pending[0] if pending else None
    
    def get_stage_questions(self, stage: InterviewStage) -> List[InterviewQuestion]:
        """Get all questions for a specific stage."""
        return [q for q in self.questions if q.stage == stage.value]
    
    def get_stage_answers(self, stage: InterviewStage) -> List[AnswerRecord]:
        """Get all answers for a specific stage."""
        return [a for a in self.answers if a.stage == stage.value]


# API Request/Response Models

class StartInterviewRequest(BaseModel):
    """Request to start a new interview."""
    resume_id: str
    job_description_id: str
    config: Optional[InterviewConfig] = None


class StartInterviewResponse(BaseModel):
    """Response after starting an interview."""
    session_id: str
    status: str
    current_stage: str
    first_question: Optional[InterviewQuestion] = None
    total_questions: int
    message: str


class SubmitAnswerRequest(BaseModel):
    """Request to submit an answer."""
    session_id: str
    answer_text: Optional[str] = None
    answer_audio_base64: Optional[str] = None  # For voice mode


class SubmitAnswerResponse(BaseModel):
    """Response after submitting an answer."""
    session_id: str
    status: str
    
    # Evaluation of submitted answer
    evaluation: Optional[Dict[str, Any]] = None
    
    # Next question (if any)
    next_question: Optional[InterviewQuestion] = None
    follow_up_question: Optional[str] = None
    
    # Progress
    current_stage: str
    questions_answered: int
    total_questions: int
    progress_percent: float
    
    # Stage transition
    stage_changed: bool = False
    interview_complete: bool = False
    
    message: str


class InterviewProgressResponse(BaseModel):
    """Response with current interview progress."""
    session_id: str
    status: str
    current_stage: str
    
    # Progress metrics
    questions_answered: int
    total_questions: int
    progress_percent: float
    
    # Score summary
    current_score: float
    stage_scores: Dict[str, float] = Field(default_factory=dict)
    
    # Time
    duration_minutes: int
    
    # Current question
    current_question: Optional[InterviewQuestion] = None


class EndInterviewRequest(BaseModel):
    """Request to end an interview early."""
    reason: Optional[str] = None


class InterviewReportResponse(BaseModel):
    """Complete interview report response."""
    session_id: str
    candidate_name: str
    role_title: str
    duration_minutes: int
    
    # Scores
    overall_score: float
    technical_score: float
    behavioral_score: float
    communication_score: float
    
    # Summary
    executive_summary: str
    strengths: List[Dict[str, str]] = Field(default_factory=list)
    concerns: List[Dict[str, str]] = Field(default_factory=list)
    
    # Recommendation
    recommendation: str
    confidence: float
    reasoning: str
    next_steps: List[str] = Field(default_factory=list)
    
    # Detailed breakdown
    question_evaluations: List[Dict[str, Any]] = Field(default_factory=list)
