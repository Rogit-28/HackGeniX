"""
Interview Orchestrator Service.

Central controller that manages complete interview sessions from start to finish.
Coordinates question generation, answer evaluation, and adaptive flow control.
"""
import asyncio
import base64
import logging
import uuid
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional, Any, Tuple, Union
from pathlib import Path
import tempfile

from src.models.interview import (
    InterviewSession,
    InterviewConfig,
    InterviewStatus,
    InterviewStage,
    InterviewMode,
    InterviewQuestion,
    AnswerRecord,
    StageProgress,
    QuestionStatus,
    StartInterviewResponse,
    SubmitAnswerResponse,
    InterviewProgressResponse,
    InterviewReportResponse,
)
from src.models.documents import ParsedResume, ParsedJobDescription
from src.models.question_bank import (
    QuestionBankConfig,
    InterviewStageHint,
)
from src.services.question_generator import (
    QuestionGenerator,
    QuestionGenerationRequest,
    GeneratedQuestion,
    get_question_generator,
)
from src.services.answer_evaluator import (
    AnswerEvaluator,
    AnswerEvaluation,
    InterviewReport,
    get_answer_evaluator,
)
from src.services.hybrid_question_selector import (
    HybridQuestionSelector,
    get_hybrid_question_selector,
)
from src.services.prompts import (
    InterviewStage as PromptStage,
    QuestionDifficulty,
)
from src.services.session_repository import get_session_repository
from src.services.semantic_matcher import get_semantic_matcher
from src.services.streaming import (
    StreamEvent,
    status_event,
    progress_event,
    result_event,
    error_event,
    done_event,
)

logger = logging.getLogger(__name__)


# Stage order for interview flow
STAGE_ORDER = [
    InterviewStage.SCREENING,
    InterviewStage.TECHNICAL,
    InterviewStage.BEHAVIORAL,
    InterviewStage.SYSTEM_DESIGN,
    InterviewStage.WRAP_UP,
]


def _get_enum_value(val):
    """Get string value from enum or string (handles Pydantic use_enum_values)."""
    return val.value if hasattr(val, 'value') else val


class InterviewOrchestrator:
    """
    Manages complete interview sessions from start to finish.
    
    Responsibilities:
    - Initialize interview with questions based on resume/JD
    - Track interview state (stage, question, time)
    - Submit answers and get evaluations
    - Adapt difficulty based on performance
    - Generate follow-up questions
    - Create final interview reports
    """
    
    def __init__(
        self,
        question_generator: Optional[QuestionGenerator] = None,
        answer_evaluator: Optional[AnswerEvaluator] = None,
        hybrid_selector: Optional[HybridQuestionSelector] = None,
    ):
        """
        Initialize the orchestrator.
        
        Args:
            question_generator: Question generation service
            answer_evaluator: Answer evaluation service
            hybrid_selector: Hybrid question selector (Phase 6.5)
        """
        self._question_generator = question_generator
        self._answer_evaluator = answer_evaluator
        self._hybrid_selector = hybrid_selector
        
        # In-memory cache backed by MongoDB persistence
        self._sessions: Dict[str, InterviewSession] = {}
        self._repo = get_session_repository()
        
        # Voice providers (lazy loaded)
        self._stt_provider = None
        self._tts_provider = None
    
    async def _save_session(self, session: InterviewSession) -> None:
        """Persist session to MongoDB (write-through cache)."""
        self._sessions[session.id] = session
        await self._repo.save(session)
    
    @property
    def question_generator(self) -> QuestionGenerator:
        if self._question_generator is None:
            self._question_generator = get_question_generator()
        return self._question_generator
    
    @property
    def answer_evaluator(self) -> AnswerEvaluator:
        if self._answer_evaluator is None:
            self._answer_evaluator = get_answer_evaluator()
        return self._answer_evaluator
    
    @property
    def hybrid_selector(self) -> HybridQuestionSelector:
        if self._hybrid_selector is None:
            self._hybrid_selector = get_hybrid_question_selector()
        return self._hybrid_selector
    
    async def _get_stt_provider(self):
        """Get STT provider (lazy load)."""
        if self._stt_provider is None:
            from src.providers.stt import get_stt_provider_async
            self._stt_provider = await get_stt_provider_async()
        return self._stt_provider
    
    async def _get_tts_provider(self):
        """Get TTS provider (lazy load)."""
        if self._tts_provider is None:
            from src.providers.tts import get_tts_provider_async
            self._tts_provider = await get_tts_provider_async()
        return self._tts_provider
    
    def _stage_to_prompt_stage(self, stage: InterviewStage) -> PromptStage:
        """Convert interview stage to prompt stage enum."""
        return PromptStage(stage.value)
    
    def _stage_to_stage_hint(self, stage: InterviewStage) -> InterviewStageHint:
        """Convert interview stage to question bank stage hint."""
        mapping = {
            InterviewStage.SCREENING: InterviewStageHint.SCREENING,
            InterviewStage.TECHNICAL: InterviewStageHint.TECHNICAL,
            InterviewStage.BEHAVIORAL: InterviewStageHint.BEHAVIORAL,
            InterviewStage.SYSTEM_DESIGN: InterviewStageHint.SYSTEM_DESIGN,
            InterviewStage.WRAP_UP: InterviewStageHint.GENERAL,
        }
        return mapping.get(stage, InterviewStageHint.TECHNICAL)
    
    def _get_stage_question_count(self, config: InterviewConfig, stage: InterviewStage) -> int:
        """Get the number of questions for a stage from config."""
        counts = {
            InterviewStage.SCREENING: config.screening_questions,
            InterviewStage.TECHNICAL: config.technical_questions,
            InterviewStage.BEHAVIORAL: config.behavioral_questions,
            InterviewStage.SYSTEM_DESIGN: config.system_design_questions,
            InterviewStage.WRAP_UP: 1,  # Always 1 wrap-up question
        }
        return counts.get(stage, 3)
    
    async def _generate_stage_questions(
        self,
        stage: InterviewStage,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        config: InterviewConfig,
        previous_questions: List[str] = None,
        match_analysis: Optional[Dict[str, Any]] = None,
    ) -> List[InterviewQuestion]:
        """Generate questions for a specific stage."""
        num_questions = self._get_stage_question_count(config, stage)
        
        if stage == InterviewStage.WRAP_UP:
            # Simple wrap-up question
            return [InterviewQuestion(
                id=str(uuid.uuid4()),
                question_text="Is there anything else you'd like to share about your experience or ask about the role?",
                stage=stage,
                difficulty="easy",
                category="wrap_up",
                purpose="Allow candidate to add final thoughts and ask questions",
                expected_answer_points=["Shows interest in role", "Asks thoughtful questions"],
                duration_seconds=180,
            )]
        
        # Map to difficulty based on stage
        difficulty_map = {
            InterviewStage.SCREENING: QuestionDifficulty.EASY,
            InterviewStage.TECHNICAL: QuestionDifficulty.MEDIUM,
            InterviewStage.BEHAVIORAL: QuestionDifficulty.MEDIUM,
            InterviewStage.SYSTEM_DESIGN: QuestionDifficulty.HARD,
        }
        
        request = QuestionGenerationRequest(
            stage=self._stage_to_prompt_stage(stage),
            num_questions=num_questions,
            difficulty=difficulty_map.get(stage, QuestionDifficulty.MEDIUM),
            focus_areas=config.focus_skills,
            exclude_topics=config.exclude_topics,
        )
        
        try:
            # Phase 6.5: Check if hybrid mode is enabled
            if config.use_question_bank:
                generated = await self._generate_hybrid_questions(
                    request=request,
                    stage=stage,
                    resume=resume,
                    jd=jd,
                    config=config,
                    previous_questions=previous_questions,
                    match_analysis=match_analysis,
                )
            else:
                # Pure LLM generation (original behavior)
                generated = await self.question_generator.generate_questions(
                    request=request,
                    resume=resume,
                    jd=jd,
                    previous_questions=previous_questions,
                    match_analysis=match_analysis,
                )
            
            # Convert to InterviewQuestion models
            questions = []
            for gq in generated:
                questions.append(InterviewQuestion(
                    id=str(uuid.uuid4()),
                    question_text=gq.question,
                    stage=stage,
                    difficulty=gq.difficulty.value,
                    category=gq.category,
                    purpose=gq.purpose,
                    expected_answer_points=gq.expected_answer_points,
                    follow_up_questions=gq.follow_up_questions,
                    duration_seconds=gq.duration_seconds,
                    competency=gq.competency,
                    source=gq.source.value if hasattr(gq, 'source') else "generated",
                ))
            
            return questions
            
        except Exception as e:
            logger.error(f"Failed to generate {stage.value} questions: {e}")
            # Return fallback questions
            return self._get_fallback_questions(stage, num_questions)
    
    async def _generate_stage_questions_stream(
        self,
        stage: InterviewStage,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        config: InterviewConfig,
        previous_questions: List[str] = None,
        match_analysis: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Union[StreamEvent, List[InterviewQuestion]]]:
        """
        Generate questions for a specific stage with SSE streaming.
        
        Same as _generate_stage_questions() but yields StreamEvent progress
        from the underlying question generator's streaming method.
        
        Yields:
            StreamEvent for progress
            List[InterviewQuestion] as the final item
        """
        num_questions = self._get_stage_question_count(config, stage)
        
        if stage == InterviewStage.WRAP_UP:
            # Simple wrap-up question — no LLM needed
            questions = [InterviewQuestion(
                id=str(uuid.uuid4()),
                question_text="Is there anything else you'd like to share about your experience or ask about the role?",
                stage=stage,
                difficulty="easy",
                category="wrap_up",
                purpose="Allow candidate to add final thoughts and ask questions",
                expected_answer_points=["Shows interest in role", "Asks thoughtful questions"],
                duration_seconds=180,
            )]
            yield questions
            return
        
        # Map to difficulty
        difficulty_map = {
            InterviewStage.SCREENING: QuestionDifficulty.EASY,
            InterviewStage.TECHNICAL: QuestionDifficulty.MEDIUM,
            InterviewStage.BEHAVIORAL: QuestionDifficulty.MEDIUM,
            InterviewStage.SYSTEM_DESIGN: QuestionDifficulty.HARD,
        }
        
        request = QuestionGenerationRequest(
            stage=self._stage_to_prompt_stage(stage),
            num_questions=num_questions,
            difficulty=difficulty_map.get(stage, QuestionDifficulty.MEDIUM),
            focus_areas=config.focus_skills,
            exclude_topics=config.exclude_topics,
        )
        
        try:
            generated = None
            
            if config.use_question_bank:
                # Hybrid mode — not streaming (still uses non-streaming hybrid path)
                generated = await self._generate_hybrid_questions(
                    request=request,
                    stage=stage,
                    resume=resume,
                    jd=jd,
                    config=config,
                    previous_questions=previous_questions,
                    match_analysis=match_analysis,
                )
            else:
                # Pure LLM generation — use streaming variant
                async for item in self.question_generator.generate_questions_stream(
                    request=request,
                    resume=resume,
                    jd=jd,
                    previous_questions=previous_questions,
                    match_analysis=match_analysis,
                ):
                    if isinstance(item, StreamEvent):
                        yield item
                    else:
                        generated = item
            
            if generated is None:
                generated = []
            
            # Convert to InterviewQuestion models
            questions = []
            for gq in generated:
                questions.append(InterviewQuestion(
                    id=str(uuid.uuid4()),
                    question_text=gq.question,
                    stage=stage,
                    difficulty=gq.difficulty.value,
                    category=gq.category,
                    purpose=gq.purpose,
                    expected_answer_points=gq.expected_answer_points,
                    follow_up_questions=gq.follow_up_questions,
                    duration_seconds=gq.duration_seconds,
                    competency=gq.competency,
                    source=gq.source.value if hasattr(gq, 'source') else "generated",
                ))
            
            yield questions
            
        except Exception as e:
            logger.error(f"Failed to generate {stage.value} questions: {e}")
            yield self._get_fallback_questions(stage, num_questions)
    
    async def _generate_hybrid_questions(
        self,
        request: QuestionGenerationRequest,
        stage: InterviewStage,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        config: InterviewConfig,
        previous_questions: Optional[List[str]] = None,
        match_analysis: Optional[Dict[str, Any]] = None,
    ) -> List[GeneratedQuestion]:
        """
        Generate questions using hybrid mode (Phase 6.5).
        
        Uses the question bank for base questions and LLM for enhancement/gap-filling.
        """
        # Build question bank config from interview config
        bank_config = QuestionBankConfig(
            use_question_bank=config.use_question_bank,
            enabled_domains=config.enabled_domains,
            auto_detect_domains=config.auto_detect_domains,
            bank_question_ratio=config.bank_question_ratio,
            allow_rephrasing=config.allow_rephrasing,
            allow_personalization=config.allow_personalization,
        )
        
        # Select questions from bank
        stage_hint = self._stage_to_stage_hint(stage)
        
        bank_questions, uncovered_skills = await self.hybrid_selector.select_questions(
            jd=jd,
            resume=resume,
            config=bank_config,
            stage=stage_hint,
            count=request.num_questions,
        )
        
        logger.info(
            f"Hybrid mode for {stage.value}: {len(bank_questions)} bank questions, "
            f"{len(uncovered_skills)} uncovered skills"
        )
        
        # Generate using hybrid method
        return await self.question_generator.generate_questions_hybrid(
            request=request,
            resume=resume,
            jd=jd,
            bank_config=bank_config,
            bank_questions=bank_questions,
            uncovered_skills=uncovered_skills,
            previous_questions=previous_questions,
            match_analysis=match_analysis,
        )
    
    def _get_fallback_questions(self, stage: InterviewStage, count: int) -> List[InterviewQuestion]:
        """Get fallback questions if generation fails."""
        fallbacks = {
            InterviewStage.SCREENING: [
                "Tell me about yourself and your background.",
                "What interests you about this position?",
                "What are your key technical strengths?",
            ],
            InterviewStage.TECHNICAL: [
                "Describe a challenging technical problem you've solved recently.",
                "How do you approach debugging complex issues?",
                "Explain a system you've designed or contributed to significantly.",
                "What's your experience with testing and code quality?",
                "How do you stay current with technology trends?",
            ],
            InterviewStage.BEHAVIORAL: [
                "Tell me about a time you had to work with a difficult team member.",
                "Describe a situation where you had to meet a tight deadline.",
                "Give an example of when you had to learn something quickly.",
            ],
            InterviewStage.SYSTEM_DESIGN: [
                "How would you design a URL shortening service?",
            ],
        }
        
        stage_fallbacks = fallbacks.get(stage, ["Tell me about your experience."])[:count]
        
        return [
            InterviewQuestion(
                id=str(uuid.uuid4()),
                question_text=q,
                stage=stage,
                difficulty="medium",
                purpose="Fallback question",
                expected_answer_points=[],
            )
            for q in stage_fallbacks
        ]
    
    async def start_interview(
        self,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        resume_id: str,
        jd_id: str,
        config: Optional[InterviewConfig] = None,
    ) -> Tuple[InterviewSession, StartInterviewResponse]:
        """
        Start a new interview session.
        
        Args:
            resume: Parsed candidate resume
            jd: Parsed job description
            resume_id: ID of the resume document
            jd_id: ID of the job description document
            config: Optional interview configuration
            
        Returns:
            Tuple of (InterviewSession, StartInterviewResponse)
        """
        config = config or InterviewConfig()
        session_id = str(uuid.uuid4())
        
        # Extract candidate name from resume
        candidate_name = "Candidate"
        if resume.contact and resume.contact.name:
            candidate_name = resume.contact.name
        
        role_title = jd.title or "Software Engineer"
        
        # Initialize session
        session = InterviewSession(
            id=session_id,
            resume_id=resume_id,
            job_description_id=jd_id,
            candidate_name=candidate_name,
            role_title=role_title,
            config=config,
            status=InterviewStatus.CREATED,
            current_stage=InterviewStage.SCREENING,
        )
        
        # Initialize stage progress
        for stage in STAGE_ORDER:
            if stage == InterviewStage.WRAP_UP:
                continue  # Skip wrap-up in progress tracking
            count = self._get_stage_question_count(config, stage)
            if count > 0:
                session.stage_progress[stage.value] = StageProgress(
                    stage=stage,
                    total_questions=count,
                )
        
        # Generate initial questions for first stage (screening)
        logger.info(f"Generating screening questions for session {session_id}")
        
        # Run match analysis before question generation
        match_analysis = None
        try:
            matcher = get_semantic_matcher()
            match_result = await matcher.match(
                resume=resume,
                job_description=jd,
                resume_id=resume_id,
                job_description_id=jd_id,
            )
            match_analysis = match_result.model_dump()
            session.match_analysis = match_analysis
            logger.info(
                f"Match analysis complete for session {session_id}: "
                f"overall={match_result.overall_score:.1f}, "
                f"matched_skills={len(match_result.matched_skills)}, "
                f"missing_skills={len(match_result.missing_skills)}"
            )
        except Exception as e:
            logger.warning(f"Match analysis failed for session {session_id}, proceeding without: {e}")
        
        screening_questions = await self._generate_stage_questions(
            stage=InterviewStage.SCREENING,
            resume=resume,
            jd=jd,
            config=config,
            match_analysis=match_analysis,
        )
        session.questions.extend(screening_questions)
        
        # Pre-generate technical questions (async in background for better UX)
        # For now, generate them upfront
        logger.info(f"Generating technical questions for session {session_id}")
        technical_questions = await self._generate_stage_questions(
            stage=InterviewStage.TECHNICAL,
            resume=resume,
            jd=jd,
            config=config,
            previous_questions=[q.question_text for q in screening_questions],
            match_analysis=match_analysis,
        )
        session.questions.extend(technical_questions)
        
        # Generate behavioral questions
        logger.info(f"Generating behavioral questions for session {session_id}")
        behavioral_questions = await self._generate_stage_questions(
            stage=InterviewStage.BEHAVIORAL,
            resume=resume,
            jd=jd,
            config=config,
            previous_questions=[q.question_text for q in session.questions],
            match_analysis=match_analysis,
        )
        session.questions.extend(behavioral_questions)
        
        # Generate system design if configured
        if config.system_design_questions > 0:
            logger.info(f"Generating system design questions for session {session_id}")
            sd_questions = await self._generate_stage_questions(
                stage=InterviewStage.SYSTEM_DESIGN,
                resume=resume,
                jd=jd,
                config=config,
                previous_questions=[q.question_text for q in session.questions],
                match_analysis=match_analysis,
            )
            session.questions.extend(sd_questions)
        
        # Add wrap-up
        wrap_up = await self._generate_stage_questions(
            stage=InterviewStage.WRAP_UP,
            resume=resume,
            jd=jd,
            config=config,
            match_analysis=match_analysis,
        )
        session.questions.extend(wrap_up)
        
        # Synthesize first question audio if voice mode
        first_question = session.current_question
        if config.mode in [InterviewMode.VOICE, InterviewMode.HYBRID] and first_question:
            await self._synthesize_question_audio(first_question, config)
        
        # Mark session as in progress
        session.status = InterviewStatus.IN_PROGRESS
        session.started_at = datetime.utcnow()
        session.last_activity_at = datetime.utcnow()
        
        # Store session (in-memory cache + MongoDB)
        await self._save_session(session)
        
        logger.info(f"Interview session {session_id} started with {len(session.questions)} questions")
        
        response = StartInterviewResponse(
            session_id=session_id,
            status=_get_enum_value(session.status),
            current_stage=_get_enum_value(session.current_stage),
            first_question=first_question,
            total_questions=len(session.questions),
            message=f"Interview started. {len(session.questions)} questions prepared across {len(session.stage_progress)} stages.",
        )
        
        return session, response
    
    async def start_interview_stream(
        self,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        resume_id: str,
        jd_id: str,
        config: Optional[InterviewConfig] = None,
    ) -> AsyncIterator[Union[StreamEvent, InterviewSession]]:
        """
        Start a new interview session with SSE streaming.
        
        Yields StreamEvent objects as progress milestones so the frontend
        can show real-time status instead of a blocking spinner.
        
        The key UX improvement: the interview is playable as soon as
        screening questions are ready (~5-8s) rather than waiting for
        ALL stages to generate (~30s+).
        
        Event flow:
            status(session_created)  → session ID available
            status(matching)         → match analysis starting
            progress(matching)       → match scores available
            result(match_complete)   → full match result
            status(generating_screening) → screening gen starting
            result(questions_ready)  → screening questions done, INTERVIEW CAN START
            status(generating_technical) → technical gen starting
            result(questions_ready)  → technical questions done
            ... (behavioral, system_design, wrap_up)
            result(interview_ready)  → all stages complete
            done                     → stream ends
        
        Yields:
            StreamEvent for progress updates
            InterviewSession as the final item (for the API layer to use)
        """
        config = config or InterviewConfig()
        session_id = str(uuid.uuid4())
        
        # Extract candidate name from resume
        candidate_name = "Candidate"
        if resume.contact and resume.contact.name:
            candidate_name = resume.contact.name
        
        role_title = jd.title or "Software Engineer"
        
        # Initialize session
        session = InterviewSession(
            id=session_id,
            resume_id=resume_id,
            job_description_id=jd_id,
            candidate_name=candidate_name,
            role_title=role_title,
            config=config,
            status=InterviewStatus.CREATED,
            current_stage=InterviewStage.SCREENING,
        )
        
        # Initialize stage progress
        for stage in STAGE_ORDER:
            if stage == InterviewStage.WRAP_UP:
                continue
            count = self._get_stage_question_count(config, stage)
            if count > 0:
                session.stage_progress[stage.value] = StageProgress(
                    stage=stage,
                    total_questions=count,
                )
        
        # --- Event: session created ---
        yield status_event("session_created", f"Session {session_id} created")
        
        # Persist initial session state
        await self._save_session(session)
        
        # --- Stage: Match analysis ---
        match_analysis = None
        try:
            yield status_event("matching", "Running resume-JD match analysis...")
            
            matcher = get_semantic_matcher()
            
            # Use streaming matcher if available
            match_result = None
            async for item in matcher.match_stream(
                resume=resume,
                job_description=jd,
                resume_id=resume_id,
                job_description_id=jd_id,
            ):
                if isinstance(item, StreamEvent):
                    # Forward matcher progress events
                    yield item
                else:
                    # Final MatchResult
                    match_result = item
            
            if match_result:
                match_analysis = match_result.model_dump()
                session.match_analysis = match_analysis
                await self._save_session(session)
                
                yield result_event(
                    "match_complete",
                    {
                        "overall_score": match_result.overall_score,
                        "skill_match_score": match_result.skill_match_score,
                        "matched_skills": match_result.matched_skills[:10],
                        "missing_skills": match_result.missing_skills[:10],
                    },
                    message=f"Match analysis complete: {match_result.overall_score:.1f}/100",
                )
                
                logger.info(
                    f"Match analysis complete for session {session_id}: "
                    f"overall={match_result.overall_score:.1f}, "
                    f"matched_skills={len(match_result.matched_skills)}, "
                    f"missing_skills={len(match_result.missing_skills)}"
                )
        except Exception as e:
            logger.warning(f"Match analysis failed for session {session_id}, proceeding without: {e}")
            yield progress_event(
                "matching",
                f"Match analysis unavailable, proceeding without: {e}",
            )
        
        # --- Stage: Generate questions progressively ---
        # Track all previously generated question texts to avoid duplicates
        all_previous_questions: List[str] = []
        
        for stage in STAGE_ORDER:
            stage_name = stage.value
            
            # Skip system_design if configured to 0 questions
            if stage == InterviewStage.SYSTEM_DESIGN and config.system_design_questions == 0:
                continue
            
            yield status_event(
                f"generating_{stage_name}",
                f"Generating {stage_name.replace('_', ' ')} questions...",
            )
            
            try:
                stage_questions = None
                async for item in self._generate_stage_questions_stream(
                    stage=stage,
                    resume=resume,
                    jd=jd,
                    config=config,
                    previous_questions=all_previous_questions if all_previous_questions else None,
                    match_analysis=match_analysis,
                ):
                    if isinstance(item, StreamEvent):
                        yield item
                    else:
                        stage_questions = item
                
                if stage_questions is None:
                    stage_questions = []
                
                session.questions.extend(stage_questions)
                all_previous_questions.extend([q.question_text for q in stage_questions])
                
                # Persist after each stage (incremental persistence)
                await self._save_session(session)
                
                # Determine if this is the first stage (screening) — interview can start
                is_first_stage = (stage == InterviewStage.SCREENING)
                
                yield result_event(
                    "questions_ready",
                    {
                        "stage": stage_name,
                        "count": len(stage_questions),
                        "total_so_far": len(session.questions),
                        "interview_playable": is_first_stage,
                        "first_question": stage_questions[0].model_dump() if stage_questions else None,
                    },
                    message=f"{stage_name.replace('_', ' ').title()}: {len(stage_questions)} questions ready",
                )
                
                logger.info(
                    f"Session {session_id}: {stage_name} — "
                    f"{len(stage_questions)} questions generated "
                    f"(total: {len(session.questions)})"
                )
                
                # After screening is ready, mark session as in-progress
                # so the frontend can start the interview immediately
                if is_first_stage:
                    session.status = InterviewStatus.IN_PROGRESS
                    session.started_at = datetime.utcnow()
                    session.last_activity_at = datetime.utcnow()
                    
                    # Synthesize first question audio if voice mode
                    first_question = session.current_question
                    if config.mode in [InterviewMode.VOICE, InterviewMode.HYBRID] and first_question:
                        await self._synthesize_question_audio(first_question, config)
                    
                    await self._save_session(session)
                    
            except Exception as e:
                logger.error(f"Failed to generate {stage_name} questions: {e}")
                yield error_event(
                    f"generating_{stage_name}",
                    f"Failed to generate {stage_name} questions: {e}",
                )
                # Don't abort — continue with remaining stages
                # (fallback questions were already returned by _generate_stage_questions)
        
        # --- Final: interview fully ready ---
        yield result_event(
            "interview_ready",
            {
                "session_id": session_id,
                "status": _get_enum_value(session.status),
                "current_stage": _get_enum_value(session.current_stage),
                "total_questions": len(session.questions),
                "first_question": session.current_question.model_dump() if session.current_question else None,
                "candidate_name": session.candidate_name,
                "role_title": session.role_title,
                "stages": {
                    stage_name: progress.total_questions
                    for stage_name, progress in session.stage_progress.items()
                },
                "message": f"Interview ready. {len(session.questions)} questions across {len(session.stage_progress)} stages.",
            },
            message=f"Interview fully ready: {len(session.questions)} questions",
        )
        
        yield done_event(f"Interview session {session_id} ready")
        
        # Yield the session object as the final item for the API layer
        yield session
    
    async def _synthesize_question_audio(
        self,
        question: InterviewQuestion,
        config: InterviewConfig,
    ) -> Optional[str]:
        """Synthesize audio for a question using TTS."""
        try:
            tts = await self._get_tts_provider()
            audio_data = await tts.synthesize(
                text=question.question_text,
                voice=config.tts_voice,
            )
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_data)
                question.audio_path = f.name
                return f.name
                
        except Exception as e:
            logger.warning(f"Failed to synthesize question audio: {e}")
            return None
    
    async def _transcribe_audio(
        self,
        audio_base64: str,
        context: Optional[List[str]] = None,
    ) -> str:
        """Transcribe audio answer using STT."""
        try:
            stt = await self._get_stt_provider()
            
            # Decode base64 audio
            audio_data = base64.b64decode(audio_base64)
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_data)
                audio_path = f.name
            
            # Transcribe
            if context:
                result = await stt.transcribe_with_interview_context(
                    audio_data=audio_path,
                    technical_terms=context,
                )
            else:
                result = await stt.transcribe(audio_data=audio_path)
            
            # Clean up temp file
            Path(audio_path).unlink(missing_ok=True)
            
            return result.text
            
        except Exception as e:
            logger.error(f"Failed to transcribe audio: {e}")
            raise ValueError(f"Audio transcription failed: {e}")
    
    async def get_session(self, session_id: str) -> Optional[InterviewSession]:
        """Get an interview session by ID (in-memory cache, MongoDB fallback)."""
        session = self._sessions.get(session_id)
        if session is None:
            session = await self._repo.load(session_id)
            if session is not None:
                self._sessions[session_id] = session
        return session
    
    def _get_next_stage(self, current_stage: InterviewStage) -> Optional[InterviewStage]:
        """Get the next stage in the interview flow."""
        try:
            current_idx = STAGE_ORDER.index(current_stage)
            if current_idx < len(STAGE_ORDER) - 1:
                return STAGE_ORDER[current_idx + 1]
        except ValueError:
            pass
        return None
    
    def _update_performance_tracking(self, session: InterviewSession, evaluation: AnswerEvaluation):
        """Update performance tracking based on latest evaluation."""
        # Update strong/weak areas based on category
        score = evaluation.scores.overall
        category = getattr(evaluation, 'category', None) or _get_enum_value(evaluation.stage)
        
        if score >= 80 and category not in session.strong_areas:
            session.strong_areas.append(category)
        elif score < 60 and category not in session.weak_areas:
            session.weak_areas.append(category)
        
        # Calculate trend
        recent_scores = [a.scores.get("overall", 0) for a in session.answers[-5:]]
        if len(recent_scores) >= 3:
            avg_recent = sum(recent_scores[-3:]) / 3
            avg_older = sum(recent_scores[:-3]) / max(len(recent_scores[:-3]), 1)
            
            if avg_recent > avg_older + 5:
                session.performance_trend = "improving"
            elif avg_recent < avg_older - 5:
                session.performance_trend = "declining"
            else:
                session.performance_trend = "stable"
    
    async def submit_answer(
        self,
        session_id: str,
        answer_text: Optional[str] = None,
        answer_audio_base64: Optional[str] = None,
    ) -> SubmitAnswerResponse:
        """
        Submit an answer for the current question.
        
        Args:
            session_id: Interview session ID
            answer_text: Text answer (for text mode)
            answer_audio_base64: Base64 encoded audio (for voice mode)
            
        Returns:
            SubmitAnswerResponse with evaluation and next question
        """
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        if session.status != InterviewStatus.IN_PROGRESS:
            raise ValueError(f"Session is not in progress: {session.status}")
        
        current_question = session.current_question
        if not current_question:
            raise ValueError("No pending questions in session")
        
        # Transcribe audio if provided
        if answer_audio_base64 and not answer_text:
            context = session.config.focus_skills or []
            answer_text = await self._transcribe_audio(answer_audio_base64, context)
        
        if not answer_text:
            raise ValueError("No answer provided")
        
        # Evaluate the answer
        stage_enum = self._stage_to_prompt_stage(InterviewStage(current_question.stage))
        
        if stage_enum == PromptStage.BEHAVIORAL and current_question.competency:
            evaluation = await self.answer_evaluator.evaluate_behavioral_answer(
                question=current_question.question_text,
                answer=answer_text,
                competency=current_question.competency,
                red_flags=[],
                green_flags=[],
                validate=True,
            )
        else:
            evaluation = await self.answer_evaluator.evaluate_answer(
                question=current_question.question_text,
                answer=answer_text,
                expected_points=current_question.expected_answer_points,
                stage=stage_enum,
                validate=True,
            )
        
        # Record the answer
        answer_record = AnswerRecord(
            question_id=current_question.id,
            question_text=current_question.question_text,
            stage=InterviewStage(current_question.stage),
            answer_text=answer_text,
            scores=evaluation.scores.to_dict(),
            strengths=evaluation.strengths,
            improvements=evaluation.improvements,
            follow_up_question=evaluation.follow_up_question,
            recommendation=evaluation.recommendation.value,
            asked_at=datetime.utcnow(),  # TODO: track actual ask time
            answered_at=datetime.utcnow(),
        )
        session.answers.append(answer_record)
        
        # Mark question as answered
        current_question.status = QuestionStatus.ANSWERED
        
        # Update stage progress
        current_stage = InterviewStage(current_question.stage)
        if current_stage.value in session.stage_progress:
            progress = session.stage_progress[current_stage.value]
            progress.answered_questions += 1
            
            # Update average score
            stage_answers = session.get_stage_answers(current_stage)
            if stage_answers:
                scores = [a.scores.get("overall", 0) for a in stage_answers]
                progress.average_score = sum(scores) / len(scores)
        
        # Update performance tracking
        self._update_performance_tracking(session, evaluation)
        
        # Determine next action
        session.last_activity_at = datetime.utcnow()
        
        # Check for follow-up
        follow_up_question = None
        if session.config.enable_follow_ups and evaluation.follow_up_question:
            # Could add follow-up logic here
            follow_up_question = evaluation.follow_up_question
        
        # Get next question
        next_question = session.current_question
        stage_changed = False
        interview_complete = False
        
        if next_question:
            next_stage = InterviewStage(next_question.stage)
            if next_stage != current_stage:
                stage_changed = True
                session.current_stage = next_stage
                
                # Mark previous stage as complete
                if current_stage.value in session.stage_progress:
                    session.stage_progress[current_stage.value].completed_at = datetime.utcnow()
                
                # Mark new stage as started
                if next_stage.value in session.stage_progress:
                    session.stage_progress[next_stage.value].started_at = datetime.utcnow()
                
                logger.info(f"Session {session_id}: Stage transition {current_stage.value} -> {next_stage.value}")
            
            # Synthesize audio for next question if voice mode
            if session.config.mode in [InterviewMode.VOICE, InterviewMode.HYBRID]:
                await self._synthesize_question_audio(next_question, session.config)
        else:
            # No more questions - interview complete
            interview_complete = True
            session.status = InterviewStatus.COMPLETED
            session.completed_at = datetime.utcnow()
            logger.info(f"Session {session_id}: Interview completed")
        
        # Persist session state after all mutations
        await self._save_session(session)
        
        # Calculate progress
        total_questions = len(session.questions)
        answered = len(session.answers)
        progress_percent = (answered / total_questions * 100) if total_questions > 0 else 0
        
        response = SubmitAnswerResponse(
            session_id=session_id,
            status=_get_enum_value(session.status),
            evaluation=evaluation.to_dict(),
            next_question=next_question,
            follow_up_question=follow_up_question,
            current_stage=_get_enum_value(session.current_stage),
            questions_answered=answered,
            total_questions=total_questions,
            progress_percent=progress_percent,
            stage_changed=stage_changed,
            interview_complete=interview_complete,
            message="Answer evaluated." + (
                " Interview complete!" if interview_complete else
                f" Moving to {_get_enum_value(session.current_stage)} stage." if stage_changed else
                ""
            ),
        )
        
        return response
    
    async def submit_answer_stream(
        self,
        session_id: str,
        answer_text: Optional[str] = None,
        answer_audio_base64: Optional[str] = None,
    ) -> AsyncIterator[Union[StreamEvent, SubmitAnswerResponse]]:
        """
        Submit an answer with SSE streaming progress.
        
        Wraps the answer submission pipeline with real-time events
        so the frontend can show transcription, evaluation, and
        scoring stages as they happen.
        
        Event flow:
            status(transcribing)     -> audio transcription (voice mode only)
            progress(transcribing)   -> transcription complete
            status(evaluating)       -> LLM evaluation starting
            progress(evaluating)     -> scores available
            status(validating)       -> hallucination check
            progress(validating)     -> validation complete
            status(updating)         -> session state update
            result(answer_evaluated) -> complete evaluation result
            done                     -> stream ends
        
        Yields:
            StreamEvent for progress
            SubmitAnswerResponse as the final item
        """
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        if session.status != InterviewStatus.IN_PROGRESS:
            raise ValueError(f"Session is not in progress: {session.status}")
        
        current_question = session.current_question
        if not current_question:
            raise ValueError("No pending questions in session")
        
        # --- Stage: Transcription (voice mode) ---
        if answer_audio_base64 and not answer_text:
            yield status_event("transcribing", "Transcribing audio answer...")
            
            context = session.config.focus_skills or []
            answer_text = await self._transcribe_audio(answer_audio_base64, context)
            
            yield progress_event(
                "transcribing",
                f"Transcription complete ({len(answer_text)} chars)",
                text_length=len(answer_text),
            )
        
        if not answer_text:
            raise ValueError("No answer provided")
        
        # --- Stage: Evaluation ---
        stage_enum = self._stage_to_prompt_stage(InterviewStage(current_question.stage))
        evaluation = None
        
        if stage_enum == PromptStage.BEHAVIORAL and current_question.competency:
            async for item in self.answer_evaluator.evaluate_behavioral_answer_stream(
                question=current_question.question_text,
                answer=answer_text,
                competency=current_question.competency,
                red_flags=[],
                green_flags=[],
                validate=True,
            ):
                if isinstance(item, StreamEvent):
                    yield item
                else:
                    evaluation = item
        else:
            async for item in self.answer_evaluator.evaluate_answer_stream(
                question=current_question.question_text,
                answer=answer_text,
                expected_points=current_question.expected_answer_points,
                stage=stage_enum,
                validate=True,
            ):
                if isinstance(item, StreamEvent):
                    yield item
                else:
                    evaluation = item
        
        if not evaluation:
            # Shouldn't happen, but guard against it
            from src.services.answer_evaluator import EvaluationScores
            evaluation = AnswerEvaluation(
                question=current_question.question_text,
                answer=answer_text,
                stage=stage_enum,
                scores=EvaluationScores(overall=50),
                notes="Evaluation failed to produce result",
            )
        
        # --- Stage: Update session state ---
        yield status_event("updating", "Updating session state...")
        
        # Record the answer
        answer_record = AnswerRecord(
            question_id=current_question.id,
            question_text=current_question.question_text,
            stage=InterviewStage(current_question.stage),
            answer_text=answer_text,
            scores=evaluation.scores.to_dict(),
            strengths=evaluation.strengths,
            improvements=evaluation.improvements,
            follow_up_question=evaluation.follow_up_question,
            recommendation=evaluation.recommendation.value,
            asked_at=datetime.utcnow(),
            answered_at=datetime.utcnow(),
        )
        session.answers.append(answer_record)
        
        # Mark question as answered
        current_question.status = QuestionStatus.ANSWERED
        
        # Update stage progress
        current_stage = InterviewStage(current_question.stage)
        if current_stage.value in session.stage_progress:
            progress_obj = session.stage_progress[current_stage.value]
            progress_obj.answered_questions += 1
            
            stage_answers = session.get_stage_answers(current_stage)
            if stage_answers:
                scores = [a.scores.get("overall", 0) for a in stage_answers]
                progress_obj.average_score = sum(scores) / len(scores)
        
        # Update performance tracking
        self._update_performance_tracking(session, evaluation)
        
        # Determine next action
        session.last_activity_at = datetime.utcnow()
        
        # Check for follow-up
        follow_up_question = None
        if session.config.enable_follow_ups and evaluation.follow_up_question:
            follow_up_question = evaluation.follow_up_question
        
        # Get next question
        next_question = session.current_question
        stage_changed = False
        interview_complete = False
        
        if next_question:
            next_stage = InterviewStage(next_question.stage)
            if next_stage != current_stage:
                stage_changed = True
                session.current_stage = next_stage
                
                if current_stage.value in session.stage_progress:
                    session.stage_progress[current_stage.value].completed_at = datetime.utcnow()
                
                if next_stage.value in session.stage_progress:
                    session.stage_progress[next_stage.value].started_at = datetime.utcnow()
                
                logger.info(f"Session {session_id}: Stage transition {current_stage.value} -> {next_stage.value}")
            
            # Synthesize audio for next question if voice mode
            if session.config.mode in [InterviewMode.VOICE, InterviewMode.HYBRID]:
                await self._synthesize_question_audio(next_question, session.config)
        else:
            interview_complete = True
            session.status = InterviewStatus.COMPLETED
            session.completed_at = datetime.utcnow()
            logger.info(f"Session {session_id}: Interview completed")
        
        # Persist session state
        await self._save_session(session)
        
        # Calculate progress
        total_questions = len(session.questions)
        answered = len(session.answers)
        progress_percent = (answered / total_questions * 100) if total_questions > 0 else 0
        
        response = SubmitAnswerResponse(
            session_id=session_id,
            status=_get_enum_value(session.status),
            evaluation=evaluation.to_dict(),
            next_question=next_question,
            follow_up_question=follow_up_question,
            current_stage=_get_enum_value(session.current_stage),
            questions_answered=answered,
            total_questions=total_questions,
            progress_percent=progress_percent,
            stage_changed=stage_changed,
            interview_complete=interview_complete,
            message="Answer evaluated." + (
                " Interview complete!" if interview_complete else
                f" Moving to {_get_enum_value(session.current_stage)} stage." if stage_changed else
                ""
            ),
        )
        
        # Final result event
        yield result_event(
            "answer_evaluated",
            {
                "session_id": session_id,
                "overall_score": evaluation.scores.overall,
                "recommendation": evaluation.recommendation.value,
                "stage_changed": stage_changed,
                "interview_complete": interview_complete,
                "questions_answered": answered,
                "total_questions": total_questions,
                "progress_percent": progress_percent,
                "next_question": next_question.model_dump() if next_question else None,
            },
            message=response.message,
        )
        
        yield done_event(f"Answer evaluation complete for session {session_id}")
        
        # Yield the response object as the final item for the API layer
        yield response
    
    async def get_progress(self, session_id: str) -> InterviewProgressResponse:
        """Get current interview progress."""
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        # Calculate stage scores
        stage_scores = {}
        for stage_name, progress in session.stage_progress.items():
            if progress.answered_questions > 0:
                stage_scores[stage_name] = progress.average_score
        
        return InterviewProgressResponse(
            session_id=session_id,
            status=_get_enum_value(session.status),
            current_stage=_get_enum_value(session.current_stage),
            questions_answered=len(session.answers),
            total_questions=len(session.questions),
            progress_percent=(len(session.answers) / len(session.questions) * 100) if session.questions else 0,
            current_score=session.overall_score,
            stage_scores=stage_scores,
            duration_minutes=session.duration_minutes,
            current_question=session.current_question,
        )
    
    async def end_interview(
        self,
        session_id: str,
        reason: Optional[str] = None,
    ) -> InterviewReportResponse:
        """
        End an interview early and generate the report.
        
        Args:
            session_id: Interview session ID
            reason: Optional reason for ending early
            
        Returns:
            Complete interview report
        """
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        # Mark as completed or cancelled
        if session.status == InterviewStatus.IN_PROGRESS:
            if len(session.answers) == 0:
                session.status = InterviewStatus.CANCELLED
            else:
                session.status = InterviewStatus.COMPLETED
            session.completed_at = datetime.utcnow()
        
        if reason:
            session.error_message = f"Ended early: {reason}"
        
        # Persist status change
        await self._save_session(session)
        
        return await self.generate_report(session_id)
    
    async def generate_report(self, session_id: str) -> InterviewReportResponse:
        """
        Generate a comprehensive interview report.
        
        Args:
            session_id: Interview session ID
            
        Returns:
            Complete interview report
        """
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        if len(session.answers) == 0:
            return InterviewReportResponse(
                session_id=session_id,
                candidate_name=session.candidate_name or "Unknown",
                role_title=session.role_title or "Unknown",
                duration_minutes=session.duration_minutes,
                overall_score=0,
                technical_score=0,
                behavioral_score=0,
                communication_score=0,
                executive_summary="Interview ended with no answers recorded.",
                recommendation="no_hire",
                confidence=0,
                reasoning="Insufficient data to evaluate candidate.",
                question_evaluations=[],
            )
        
        # Convert answer records to AnswerEvaluation objects for report generation
        from src.services.answer_evaluator import EvaluationScores, AnswerStrength
        
        evaluations = []
        for answer in session.answers:
            stage_enum = PromptStage(answer.stage.value if hasattr(answer.stage, 'value') else answer.stage)
            
            eval_obj = AnswerEvaluation(
                question=answer.question_text,
                answer=answer.answer_text,
                stage=stage_enum,
                scores=EvaluationScores.from_dict(answer.scores),
                strengths=answer.strengths,
                improvements=answer.improvements,
                follow_up_question=answer.follow_up_question,
                recommendation=AnswerStrength(answer.recommendation),
            )
            evaluations.append(eval_obj)
        
        # Generate report using evaluator
        report = await self.answer_evaluator.generate_interview_report(
            candidate_name=session.candidate_name or "Candidate",
            role_title=session.role_title or "Software Engineer",
            duration_minutes=session.duration_minutes,
            evaluations=evaluations,
        )
        
        return InterviewReportResponse(
            session_id=session_id,
            candidate_name=report.candidate_name,
            role_title=report.role_title,
            duration_minutes=report.duration_minutes,
            overall_score=report.overall_score,
            technical_score=report.technical_score,
            behavioral_score=report.behavioral_score,
            communication_score=report.communication_score,
            executive_summary=report.executive_summary,
            strengths=report.strengths,
            concerns=report.concerns,
            recommendation=_get_enum_value(report.recommendation),
            confidence=report.confidence,
            reasoning=report.reasoning,
            next_steps=report.next_steps,
            question_evaluations=[e.to_dict() for e in report.evaluations],
        )
    
    async def export_pdf(self, session_id: str, save_path: Optional[str] = None) -> bytes:
        """
        Generate a PDF report for a completed interview.
        
        Args:
            session_id: Interview session ID
            save_path: Optional path to save the PDF (uses default if None)
            
        Returns:
            PDF content as bytes
        """
        from src.models.report import (
            FullInterviewReport,
            ReportMetadata,
            CandidateInfo,
            ScoreBreakdown,
            ScoreSection,
            QuestionSummary,
            ReportStrength,
            ReportConcern,
            HiringRecommendation,
            RecommendationDecision,
            SeverityLevel,
        )
        from src.services.pdf_generator import PDFReportGenerator
        
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        # Generate the report data first
        report_response = await self.generate_report(session_id)
        
        # Build metadata
        metadata = ReportMetadata(session_id=session_id)
        
        # Build candidate info
        interview_date = session.started_at or session.created_at
        candidate = CandidateInfo(
            name=report_response.candidate_name,
            role_title=report_response.role_title,
            interview_date=interview_date,
            duration_minutes=report_response.duration_minutes,
        )
        
        # Build score breakdown
        scores = ScoreBreakdown(
            overall=ScoreSection(
                category="Overall",
                score=report_response.overall_score,
                description="Composite score across all evaluation areas",
            ),
            technical=ScoreSection(
                category="Technical",
                score=report_response.technical_score,
                description="Technical knowledge and problem-solving ability",
            ),
            behavioral=ScoreSection(
                category="Behavioral",
                score=report_response.behavioral_score,
                description="Soft skills, teamwork, and cultural fit",
            ),
            communication=ScoreSection(
                category="Communication",
                score=report_response.communication_score,
                description="Clarity, articulation, and professional communication",
            ),
        )
        
        # Build strengths
        strengths = []
        for s in report_response.strengths:
            if isinstance(s, dict):
                strengths.append(ReportStrength(
                    title=s.get("title", s.get("area", "Strength")),
                    evidence=s.get("evidence", s.get("description", str(s))),
                    impact_level=s.get("impact", "medium"),
                ))
            elif isinstance(s, str):
                strengths.append(ReportStrength(title="Strength", evidence=s))
        
        # Build concerns
        concerns = []
        for c in report_response.concerns:
            if isinstance(c, dict):
                severity_str = c.get("severity", "medium")
                try:
                    severity = SeverityLevel(severity_str)
                except ValueError:
                    severity = SeverityLevel.MEDIUM
                concerns.append(ReportConcern(
                    title=c.get("title", c.get("area", "Concern")),
                    evidence=c.get("evidence", c.get("description", str(c))),
                    severity=severity,
                    suggestion=c.get("suggestion"),
                ))
            elif isinstance(c, str):
                concerns.append(ReportConcern(title="Area for Improvement", evidence=c))
        
        # Build question evaluations
        question_evals = []
        for i, e in enumerate(report_response.question_evaluations):
            question_evals.append(QuestionSummary(
                question_id=e.get("question_id", f"q_{i}"),
                question_text=e.get("question", ""),
                answer_text=e.get("answer", ""),
                stage=e.get("stage", "unknown"),
                score=e.get("scores", {}).get("overall", 0),
                strengths=e.get("strengths", []),
                improvements=e.get("improvements", []),
                key_feedback=e.get("notes"),
                recommendation=e.get("recommendation", "acceptable"),
            ))
        
        # Build recommendation
        try:
            decision = RecommendationDecision(report_response.recommendation)
        except ValueError:
            decision = RecommendationDecision.NO_HIRE
        
        recommendation = HiringRecommendation(
            decision=decision,
            confidence_percent=report_response.confidence,
            reasoning=report_response.reasoning,
            next_steps=report_response.next_steps,
        )
        
        # Create full report
        full_report = FullInterviewReport(
            metadata=metadata,
            candidate=candidate,
            executive_summary=report_response.executive_summary,
            scores=scores,
            strengths=strengths,
            concerns=concerns,
            question_evaluations=question_evals,
            recommendation=recommendation,
        )
        
        # Generate PDF
        generator = PDFReportGenerator(full_report)
        
        if save_path:
            generator.save(save_path)
            with open(save_path, "rb") as f:
                return f.read()
        else:
            return generator.generate()
    
    async def pause_interview(self, session_id: str) -> InterviewSession:
        """Pause an interview session."""
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        if session.status == InterviewStatus.IN_PROGRESS:
            session.status = InterviewStatus.PAUSED
            session.last_activity_at = datetime.utcnow()
            await self._save_session(session)
            logger.info(f"Session {session_id} paused")
        
        return session
    
    async def resume_interview(self, session_id: str) -> InterviewSession:
        """Resume a paused interview session."""
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        if session.status == InterviewStatus.PAUSED:
            session.status = InterviewStatus.IN_PROGRESS
            session.last_activity_at = datetime.utcnow()
            await self._save_session(session)
            logger.info(f"Session {session_id} resumed")
        
        return session
    
    async def list_sessions(
        self,
        status: Optional[InterviewStatus] = None,
        limit: int = 50,
    ) -> List[InterviewSession]:
        """List interview sessions, optionally filtered by status."""
        return await self._repo.list(status=status, limit=limit)
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete an interview session."""
        # Remove from in-memory cache
        self._sessions.pop(session_id, None)
        # Remove from MongoDB
        deleted = await self._repo.delete(session_id)
        if deleted:
            logger.info(f"Session {session_id} deleted")
        return deleted


# Global instance (lazy loaded)
_orchestrator: Optional[InterviewOrchestrator] = None


def get_interview_orchestrator() -> InterviewOrchestrator:
    """Get or create the interview orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = InterviewOrchestrator()
    return _orchestrator
