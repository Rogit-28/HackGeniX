"""
Pydantic models for interview sessions.
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


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
    source: str = "generated"  # bank, bank_rephrased, bank_personalized, generated, follow_up, augmented
    
    # Phase 7: Question augmentation tracking
    parent_question_id: Optional[str] = None       # ID of parent question (for follow-up sub-questions)
    sub_question_number: Optional[int] = None       # e.g. 1 for "Q3a", 2 for "Q3b"
    original_question_text: Optional[str] = None    # Original text before augmentation
    
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
    """Configuration for an interview session.
    
    Defaults are loaded from config/interview.yaml.  Per-session overrides
    (passed via the API request body) take precedence.
    """
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
    enable_question_augmentation: bool = True  # Phase 7: Augment questions based on candidate answers
    
    # Follow-up "don't know" / depth settings
    max_follow_ups_after_dont_know: int = 1
    require_follow_up_depth_increase: bool = True
    allow_different_angle_on_failure: bool = True
    hooks_trigger_alone: bool = False
    
    # Follow-up trigger rule thresholds
    poor_score_threshold: float = 40
    poor_recommendations: List[str] = Field(default_factory=lambda: ["weak", "insufficient", "concerning"])
    standout_score_threshold: float = 70
    
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

    @model_validator(mode="before")
    @classmethod
    def _apply_yaml_defaults(cls, values: Any) -> Any:
        """Load defaults from config/interview.yaml, then overlay per-session overrides."""
        if not isinstance(values, dict):
            return values

        try:
            from src.core.config import get_interview_config
            cfg = get_interview_config()
        except Exception:
            # If config file is missing or malformed, fall back to field defaults
            logger.debug("interview.yaml not loaded; using field defaults")
            return values

        # Build a flat mapping from the nested YAML structure to model fields.
        yaml_defaults: Dict[str, Any] = {}

        # questions.*
        q = cfg.get("questions", {})
        if "screening" in q:
            yaml_defaults["screening_questions"] = q["screening"]
        if "technical" in q:
            yaml_defaults["technical_questions"] = q["technical"]
        if "behavioral" in q:
            yaml_defaults["behavioral_questions"] = q["behavioral"]
        if "system_design" in q:
            yaml_defaults["system_design_questions"] = q["system_design"]

        # time_limits.*
        tl = cfg.get("time_limits", {})
        if "max_duration_seconds" in tl:
            yaml_defaults["max_duration_seconds"] = tl["max_duration_seconds"]
        if "question_timeout_seconds" in tl:
            yaml_defaults["question_timeout_seconds"] = tl["question_timeout_seconds"]

        # question_generation.*
        qg = cfg.get("question_generation", {})
        for key in ("use_question_bank", "auto_detect_domains", "bank_question_ratio",
                     "allow_rephrasing", "allow_personalization"):
            if key in qg:
                yaml_defaults[key] = qg[key]

        # adaptive.*
        ad = cfg.get("adaptive", {})
        if "adaptive_difficulty" in ad:
            yaml_defaults["adaptive_difficulty"] = ad["adaptive_difficulty"]
        if "enable_question_augmentation" in ad:
            yaml_defaults["enable_question_augmentation"] = ad["enable_question_augmentation"]

        # follow_ups.*
        fu = cfg.get("follow_ups", {})
        if "enabled" in fu:
            yaml_defaults["enable_follow_ups"] = fu["enabled"]
        if "max_per_question" in fu:
            yaml_defaults["max_follow_ups_per_question"] = fu["max_per_question"]
        if "max_after_dont_know" in fu:
            yaml_defaults["max_follow_ups_after_dont_know"] = fu["max_after_dont_know"]
        if "require_depth_increase" in fu:
            yaml_defaults["require_follow_up_depth_increase"] = fu["require_depth_increase"]
        if "allow_different_angle_on_failure" in fu:
            yaml_defaults["allow_different_angle_on_failure"] = fu["allow_different_angle_on_failure"]

        # follow_ups.trigger_rules.*
        tr = fu.get("trigger_rules", {})
        if "poor_score_threshold" in tr:
            yaml_defaults["poor_score_threshold"] = tr["poor_score_threshold"]
        if "poor_recommendations" in tr:
            yaml_defaults["poor_recommendations"] = tr["poor_recommendations"]
        if "standout_score_threshold" in tr:
            yaml_defaults["standout_score_threshold"] = tr["standout_score_threshold"]
        if "hooks_trigger_alone" in tr:
            yaml_defaults["hooks_trigger_alone"] = tr["hooks_trigger_alone"]

        # voice.*
        v = cfg.get("voice", {})
        if "tts_voice" in v:
            yaml_defaults["tts_voice"] = v["tts_voice"]
        if "stt_model" in v:
            yaml_defaults["stt_model"] = v["stt_model"]

        # Merge: yaml_defaults first, then per-session overrides on top
        merged = {**yaml_defaults, **values}
        return merged
    
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
    
    # Match analysis (computed at interview start from semantic matcher)
    match_analysis: Optional[Dict[str, Any]] = None
    
    # Phase 7: Candidate context for question augmentation
    candidate_context: Optional[Dict[str, Any]] = None
    follow_up_count: int = 0  # Total follow-up sub-questions inserted so far
    
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
