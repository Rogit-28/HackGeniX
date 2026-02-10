"""
Question Generation Service.

Generates interview questions using LLM based on job description,
candidate resume, and interview stage.

Supports hybrid mode (Phase 6.5):
- Base questions from curated question bank (60-70%)
- LLM rephrases/personalizes bank questions
- LLM generates gap-filling questions for uncovered skills
"""
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from src.providers.llm import (
    BaseLLMProvider,
    Message,
    GenerationConfig,
    system_message,
    user_message,
    get_llm_provider_sync,
)
from src.services.prompts import (
    InterviewStage,
    QuestionDifficulty,
    INTERVIEWER_SYSTEM_PROMPT,
    QUESTION_GENERATION_PROMPTS,
    FOLLOW_UP_PROMPT,
    DIFFICULTY_ADJUSTMENT_PROMPT,
    ENHANCE_BANK_QUESTION_PROMPT,
    GAP_FILLING_QUESTION_PROMPT,
    BATCH_ENHANCE_QUESTIONS_PROMPT,
)
from src.models.documents import ParsedResume, ParsedJobDescription
from src.models.question_bank import (
    BankQuestion,
    QuestionBankConfig,
    QuestionSource,
    InterviewStageHint,
    EnrichedQuestion,
)

logger = logging.getLogger(__name__)


@dataclass
class GeneratedQuestion:
    """A generated interview question with metadata."""
    question: str
    stage: InterviewStage
    difficulty: QuestionDifficulty
    category: Optional[str] = None
    purpose: str = ""
    expected_answer_points: List[str] = field(default_factory=list)
    follow_up_questions: List[str] = field(default_factory=list)
    duration_seconds: int = 120
    competency: Optional[str] = None  # For behavioral questions
    source: QuestionSource = QuestionSource.GENERATED  # Phase 6.5: Track question origin
    original_bank_question: Optional[str] = None  # Original bank question text if from bank
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "stage": self.stage.value,
            "difficulty": self.difficulty.value,
            "category": self.category,
            "purpose": self.purpose,
            "expected_answer_points": self.expected_answer_points,
            "follow_up_questions": self.follow_up_questions,
            "duration_seconds": self.duration_seconds,
            "competency": self.competency,
            "source": self.source.value,
            "original_bank_question": self.original_bank_question,
        }


@dataclass
class QuestionGenerationRequest:
    """Request parameters for question generation."""
    stage: InterviewStage
    num_questions: int = 5
    difficulty: QuestionDifficulty = QuestionDifficulty.MEDIUM
    focus_areas: List[str] = field(default_factory=list)
    exclude_topics: List[str] = field(default_factory=list)


class QuestionGenerator:
    """
    Service for generating interview questions using LLM.
    
    Generates contextual questions based on:
    - Job description requirements
    - Candidate's resume and experience
    - Interview stage (screening, technical, behavioral)
    - Previous questions asked (to avoid repetition)
    """
    
    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        """
        Initialize the question generator.
        
        Args:
            llm_provider: LLM provider instance. If None, uses default from factory.
        """
        self.llm = llm_provider or get_llm_provider_sync()
        self._generation_config = GenerationConfig(
            max_tokens=2048,
            temperature=0.7,  # Some creativity in questions
            top_p=0.9,
        )
    
    def _build_resume_summary(self, resume: ParsedResume) -> str:
        """Build a concise summary of the resume for prompts."""
        parts = []
        
        if resume.summary:
            parts.append(f"Summary: {resume.summary[:500]}")
        
        if resume.skills:
            parts.append(f"Skills: {', '.join(resume.skills[:20])}")
        
        if resume.experience:
            exp_summary = []
            for exp in resume.experience[:3]:
                try:
                    # Handle both Experience objects and dicts
                    if isinstance(exp, dict):
                        title = exp.get("title")
                        company = exp.get("company")
                    else:
                        title = exp.title
                        company = exp.company
                    
                    if title and company:
                        exp_summary.append(f"{title} at {company}")
                except Exception:
                    continue
            if exp_summary:
                parts.append(f"Experience: {'; '.join(exp_summary)}")
        
        if resume.education:
            edu_summary = []
            for edu in resume.education[:2]:
                if edu.degree and edu.institution:
                    edu_summary.append(f"{edu.degree} from {edu.institution}")
            if edu_summary:
                parts.append(f"Education: {'; '.join(edu_summary)}")
        
        return "\n".join(parts) if parts else "No resume details available"
    
    def _build_jd_summary(self, jd: ParsedJobDescription) -> str:
        """Build a concise summary of the job description for prompts."""
        parts = []
        
        if jd.title:
            parts.append(f"Role: {jd.title}")
        
        if jd.required_skills:
            parts.append(f"Required Skills: {', '.join(jd.required_skills[:15])}")
        
        if jd.preferred_skills:
            parts.append(f"Preferred Skills: {', '.join(jd.preferred_skills[:10])}")
        
        if jd.experience_years_min:
            parts.append(f"Experience Required: {jd.experience_years_min}+ years")
        
        if jd.responsibilities:
            parts.append(f"Key Responsibilities: {'; '.join(jd.responsibilities[:5])}")
        
        return "\n".join(parts) if parts else "No JD details available"
    
    def _build_match_context(self, match_analysis: Optional[Dict[str, Any]]) -> str:
        """Build a match context string from semantic matcher results for prompt injection."""
        if not match_analysis:
            return ""
        
        lines = []
        lines.append("=== Candidate-JD Match Analysis ===")
        
        # Scores overview
        overall = match_analysis.get("overall_score")
        skill_score = match_analysis.get("skill_match_score")
        exp_score = match_analysis.get("experience_match_score")
        if overall is not None:
            lines.append(f"Overall match: {overall:.0f}/100 (skill: {skill_score:.0f}, experience: {exp_score:.0f})")
        
        # Matched skills
        matched = match_analysis.get("matched_skills", [])
        if matched:
            lines.append(f"Matched skills: {', '.join(matched)}")
        
        # Missing skills
        missing = match_analysis.get("missing_skills", [])
        if missing:
            lines.append(f"Missing skills: {', '.join(missing)}")
        
        # Transferable skills
        transferable = match_analysis.get("transferable_skills", [])
        if transferable:
            parts = []
            for t in transferable:
                if isinstance(t, dict):
                    src = t.get("from", t.get("source", "?"))
                    tgt = t.get("to", t.get("target", "?"))
                    parts.append(f"{src} -> {tgt}")
                else:
                    parts.append(str(t))
            lines.append(f"Transferable skills: {', '.join(parts)}")
        
        # Risk flags
        risk_flags = match_analysis.get("risk_flags", [])
        if risk_flags:
            lines.append(f"Risk flags: {'; '.join(risk_flags)}")
        
        # Strengths
        strengths = match_analysis.get("strengths", [])
        if strengths:
            lines.append(f"Strengths: {'; '.join(strengths)}")
        
        # Experience quality
        exp_quality = match_analysis.get("experience_quality")
        if exp_quality:
            reasoning = match_analysis.get("experience_quality_reasoning", "")
            lines.append(f"Experience quality: {exp_quality}" + (f" ({reasoning})" if reasoning else ""))
        
        # LLM reasoning (from sidecar)
        llm_reasoning = match_analysis.get("llm_reasoning")
        if llm_reasoning:
            lines.append(f"Fit assessment: {llm_reasoning[:300]}")
        
        lines.append("===")
        
        return "\n".join(lines)
    
    def _parse_llm_json_response(self, response: str) -> List[Dict[str, Any]]:
        """Parse JSON from LLM response, handling common formatting issues."""
        # Try to find JSON array in response
        response = response.strip()
        
        # Handle markdown code blocks
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            response = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            response = response[start:end].strip()
        
        # Try to find array bounds
        if not response.startswith("["):
            start = response.find("[")
            if start != -1:
                response = response[start:]
        
        if not response.endswith("]"):
            end = response.rfind("]")
            if end != -1:
                response = response[:end + 1]
        
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            logger.debug(f"Response was: {response[:500]}")
            return []
    
    async def generate_questions(
        self,
        request: QuestionGenerationRequest,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        previous_questions: Optional[List[str]] = None,
        match_analysis: Optional[Dict[str, Any]] = None,
    ) -> List[GeneratedQuestion]:
        """
        Generate interview questions for a specific stage.
        
        Args:
            request: Question generation parameters
            resume: Parsed candidate resume
            jd: Parsed job description
            previous_questions: Previously asked questions to avoid
            match_analysis: Match analysis dict from semantic matcher (optional)
            
        Returns:
            List of generated questions with metadata
        """
        stage = request.stage
        
        # Get the appropriate prompt template
        if stage not in QUESTION_GENERATION_PROMPTS:
            raise ValueError(f"No prompt template for stage: {stage}")
        
        prompt_template = QUESTION_GENERATION_PROMPTS[stage]
        
        # Build context based on stage
        context = {
            "num_questions": request.num_questions,
            "role_title": jd.title or "Software Engineer",
            "jd_summary": self._build_jd_summary(jd),
            "resume_summary": self._build_resume_summary(resume),
            "required_skills": ", ".join(jd.required_skills[:15]),
            "technical_background": self._build_resume_summary(resume),
            "focus_areas": ", ".join(request.focus_areas) if request.focus_areas else "general technical skills",
            "experience_summary": self._build_resume_summary(resume),
            "competencies": "leadership, problem-solving, teamwork, communication, adaptability",
            "technical_requirements": ", ".join(jd.required_skills[:10]),
            "system_experience": "Based on resume experience",
            "complexity_level": "appropriate for candidate experience",
            "match_context": self._build_match_context(match_analysis),
        }
        
        # Format the prompt
        prompt = prompt_template.format(**context)
        
        # Add exclusion note if there are previous questions
        if previous_questions:
            prompt += f"\n\nAvoid questions similar to these already asked:\n"
            for q in previous_questions[:10]:
                prompt += f"- {q}\n"
        
        # Generate questions using LLM
        messages = [
            system_message(INTERVIEWER_SYSTEM_PROMPT),
            user_message(prompt),
        ]
        
        try:
            response = await self.llm.generate(messages, self._generation_config)
            questions_data = self._parse_llm_json_response(response.content)
            
            # Convert to GeneratedQuestion objects
            questions = []
            for q_data in questions_data:
                if isinstance(q_data, dict) and "question" in q_data:
                    questions.append(GeneratedQuestion(
                        question=q_data["question"],
                        stage=stage,
                        difficulty=QuestionDifficulty(q_data.get("difficulty", "medium")),
                        category=q_data.get("category"),
                        purpose=q_data.get("purpose", ""),
                        expected_answer_points=q_data.get("expected_answer_points", []),
                        follow_up_questions=q_data.get("follow_up_questions", []),
                        duration_seconds=q_data.get("duration_seconds", 120),
                        competency=q_data.get("competency"),
                    ))
            
            logger.info(f"Generated {len(questions)} {stage.value} questions")
            return questions
            
        except Exception as e:
            logger.error(f"Failed to generate questions: {e}")
            raise
    
    async def generate_follow_up(
        self,
        original_question: str,
        candidate_answer: str,
        evaluation_summary: str,
    ) -> Optional[str]:
        """
        Generate a follow-up question based on candidate's answer.
        
        Args:
            original_question: The question that was asked
            candidate_answer: The candidate's response
            evaluation_summary: Brief evaluation of the answer
            
        Returns:
            Follow-up question or None if not needed
        """
        prompt = FOLLOW_UP_PROMPT.format(
            original_question=original_question,
            answer=candidate_answer,
            evaluation_summary=evaluation_summary,
        )
        
        messages = [
            system_message(INTERVIEWER_SYSTEM_PROMPT),
            user_message(prompt),
        ]
        
        try:
            response = await self.llm.generate(messages, GenerationConfig(
                max_tokens=512,
                temperature=0.6,
            ))
            
            # Parse response
            result = self._parse_llm_json_response(f"[{response.content}]")
            if result and isinstance(result[0], dict):
                return result[0].get("follow_up_question")
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to generate follow-up: {e}")
            return None
    
    async def adjust_difficulty(
        self,
        performance_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Determine appropriate difficulty for next question based on performance.
        
        Args:
            performance_summary: Summary of candidate's performance so far
            
        Returns:
            Difficulty adjustment recommendation
        """
        prompt = DIFFICULTY_ADJUSTMENT_PROMPT.format(
            questions_answered=performance_summary.get("questions_answered", 0),
            average_score=performance_summary.get("average_score", 0),
            trend=performance_summary.get("trend", "stable"),
            strong_areas=", ".join(performance_summary.get("strong_areas", [])),
            weak_areas=", ".join(performance_summary.get("weak_areas", [])),
            current_difficulty=performance_summary.get("current_difficulty", "medium"),
        )
        
        messages = [
            system_message(INTERVIEWER_SYSTEM_PROMPT),
            user_message(prompt),
        ]
        
        try:
            response = await self.llm.generate(messages, GenerationConfig(
                max_tokens=512,
                temperature=0.3,  # More deterministic
            ))
            
            result = self._parse_llm_json_response(f"[{response.content}]")
            if result and isinstance(result[0], dict):
                return result[0]
            
            return {"next_difficulty": "medium", "difficulty_change": "maintain"}
            
        except Exception as e:
            logger.error(f"Failed to adjust difficulty: {e}")
            return {"next_difficulty": "medium", "difficulty_change": "maintain"}
    
    async def generate_screening_questions(
        self,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        num_questions: int = 3,
    ) -> List[GeneratedQuestion]:
        """Convenience method for generating screening questions."""
        request = QuestionGenerationRequest(
            stage=InterviewStage.SCREENING,
            num_questions=num_questions,
            difficulty=QuestionDifficulty.EASY,
        )
        return await self.generate_questions(request, resume, jd)
    
    async def generate_technical_questions(
        self,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        num_questions: int = 5,
        focus_areas: Optional[List[str]] = None,
    ) -> List[GeneratedQuestion]:
        """Convenience method for generating technical questions."""
        request = QuestionGenerationRequest(
            stage=InterviewStage.TECHNICAL,
            num_questions=num_questions,
            difficulty=QuestionDifficulty.MEDIUM,
            focus_areas=focus_areas or [],
        )
        return await self.generate_questions(request, resume, jd)
    
    async def generate_behavioral_questions(
        self,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        num_questions: int = 3,
    ) -> List[GeneratedQuestion]:
        """Convenience method for generating behavioral questions."""
        request = QuestionGenerationRequest(
            stage=InterviewStage.BEHAVIORAL,
            num_questions=num_questions,
            difficulty=QuestionDifficulty.MEDIUM,
        )
        return await self.generate_questions(request, resume, jd)
    
    # =========================================================================
    # Phase 6.5: Hybrid Question Generation Methods
    # =========================================================================
    
    async def generate_questions_hybrid(
        self,
        request: QuestionGenerationRequest,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        bank_config: QuestionBankConfig,
        bank_questions: List[BankQuestion],
        uncovered_skills: List[str],
        previous_questions: Optional[List[str]] = None,
        match_analysis: Optional[Dict[str, Any]] = None,
    ) -> List[GeneratedQuestion]:
        """
        Generate questions using hybrid approach.
        
        This method:
        1. Enhances/personalizes bank questions with LLM
        2. Generates gap-filling questions for uncovered skills
        3. Combines and returns both with proper source tagging
        
        Args:
            request: Question generation parameters
            resume: Parsed candidate resume
            jd: Parsed job description
            bank_config: Question bank configuration
            bank_questions: Pre-selected questions from the bank
            uncovered_skills: Skills not covered by bank (for gap-filling)
            previous_questions: Previously asked questions to avoid
            match_analysis: Match analysis dict from semantic matcher (optional)
            
        Returns:
            List of generated questions with source tags
        """
        logger.info(
            f"Hybrid generation: {len(bank_questions)} bank questions, "
            f"{len(uncovered_skills)} uncovered skills"
        )
        
        all_questions: List[GeneratedQuestion] = []
        
        # Step 1: Enhance bank questions (if any)
        if bank_questions:
            enhanced = await self._enhance_bank_questions(
                bank_questions=bank_questions,
                resume=resume,
                jd=jd,
                config=bank_config,
            )
            all_questions.extend(enhanced)
            logger.info(f"Enhanced {len(enhanced)} bank questions")
        
        # Step 2: Generate gap-filling questions for uncovered skills
        gap_count = request.num_questions - len(all_questions)
        
        if gap_count > 0 and uncovered_skills:
            # Get example questions from bank for style matching
            example_questions = [q.question_text for q in bank_questions[:3]]
            
            gap_questions = await self._generate_gap_questions(
                uncovered_skills=uncovered_skills,
                resume=resume,
                jd=jd,
                stage=request.stage,
                difficulty=request.difficulty,
                count=gap_count,
                example_questions=example_questions,
                previous_questions=previous_questions,
            )
            all_questions.extend(gap_questions)
            logger.info(f"Generated {len(gap_questions)} gap-filling questions")
        
        # Step 3: If still need more questions, fall back to full LLM generation
        remaining = request.num_questions - len(all_questions)
        if remaining > 0:
            logger.info(f"Generating {remaining} additional questions via pure LLM")
            fallback_request = QuestionGenerationRequest(
                stage=request.stage,
                num_questions=remaining,
                difficulty=request.difficulty,
                focus_areas=request.focus_areas,
                exclude_topics=request.exclude_topics,
            )
            # Combine previous questions with already generated ones
            avoid_questions = previous_questions or []
            avoid_questions.extend([q.question for q in all_questions])
            
            fallback = await self.generate_questions(
                fallback_request, resume, jd, avoid_questions, match_analysis
            )
            all_questions.extend(fallback)
        
        logger.info(
            f"Hybrid generation complete: {len(all_questions)} total questions "
            f"({sum(1 for q in all_questions if q.source != QuestionSource.GENERATED)} from bank)"
        )
        
        return all_questions[:request.num_questions]
    
    async def _enhance_bank_questions(
        self,
        bank_questions: List[BankQuestion],
        resume: ParsedResume,
        jd: ParsedJobDescription,
        config: QuestionBankConfig,
    ) -> List[GeneratedQuestion]:
        """
        Enhance bank questions by rephrasing and/or personalizing.
        
        Args:
            bank_questions: Questions from the bank to enhance
            resume: Parsed candidate resume
            jd: Parsed job description
            config: Question bank configuration
            
        Returns:
            List of enhanced GeneratedQuestion objects
        """
        if not bank_questions:
            return []
        
        # If no enhancement enabled, return as-is
        if not config.allow_rephrasing and not config.allow_personalization:
            return [
                self._bank_question_to_generated(q, QuestionSource.BANK)
                for q in bank_questions
            ]
        
        # Use batch enhancement for efficiency
        if len(bank_questions) > 1:
            return await self._batch_enhance_questions(
                bank_questions, resume, jd, config
            )
        
        # Single question enhancement
        enhanced = []
        for bank_q in bank_questions:
            try:
                enhanced_q = await self._enhance_single_question(
                    bank_q, resume, jd, config
                )
                enhanced.append(enhanced_q)
            except Exception as e:
                logger.warning(f"Failed to enhance question, using original: {e}")
                enhanced.append(
                    self._bank_question_to_generated(bank_q, QuestionSource.BANK)
                )
        
        return enhanced
    
    async def _enhance_single_question(
        self,
        bank_question: BankQuestion,
        resume: ParsedResume,
        jd: ParsedJobDescription,
        config: QuestionBankConfig,
    ) -> GeneratedQuestion:
        """Enhance a single bank question with LLM."""
        # Build context
        resume_summary = self._build_resume_summary(resume)
        jd_summary = self._build_jd_summary(jd)
        
        # Find relevant experience for personalization
        relevant_exp = self._find_relevant_experience(
            resume, bank_question.skills
        )
        
        prompt = ENHANCE_BANK_QUESTION_PROMPT.format(
            bank_question=bank_question.question_text,
            domain=bank_question.domain,
            category=bank_question.category.value,
            difficulty=bank_question.difficulty.value,
            resume_summary=resume_summary,
            relevant_experience=relevant_exp or "No directly relevant experience found",
            jd_requirements=jd_summary,
        )
        
        messages = [
            system_message(INTERVIEWER_SYSTEM_PROMPT),
            user_message(prompt),
        ]
        
        response = await self.llm.generate(
            messages,
            GenerationConfig(max_tokens=512, temperature=0.6)
        )
        
        enhanced_text = response.content.strip()
        
        # Remove any leading "Rephrased Question:" or similar prefixes
        prefixes = [
            "Rephrased Question:", "Enhanced Question:", "Question:",
            "Here is the rephrased question:", "Rephrased:"
        ]
        for prefix in prefixes:
            if enhanced_text.lower().startswith(prefix.lower()):
                enhanced_text = enhanced_text[len(prefix):].strip()
        
        # Determine source based on what was applied
        source = QuestionSource.BANK_REPHRASED
        if config.allow_personalization and relevant_exp:
            source = QuestionSource.BANK_PERSONALIZED
        
        return GeneratedQuestion(
            question=enhanced_text,
            stage=self._map_stage_hint_to_stage(bank_question.stage_hint),
            difficulty=QuestionDifficulty(bank_question.difficulty.value),
            category=bank_question.category.value,
            purpose=f"Evaluate {', '.join(bank_question.skills[:3])} skills",
            expected_answer_points=[],
            follow_up_questions=[],
            duration_seconds=120,
            source=source,
            original_bank_question=bank_question.question_text,
        )
    
    async def _batch_enhance_questions(
        self,
        bank_questions: List[BankQuestion],
        resume: ParsedResume,
        jd: ParsedJobDescription,
        config: QuestionBankConfig,
    ) -> List[GeneratedQuestion]:
        """Batch enhance multiple questions in a single LLM call."""
        # Prepare questions JSON
        questions_json = json.dumps([
            {
                "id": q.id,
                "question": q.question_text,
                "domain": q.domain,
                "category": q.category.value,
                "skills": q.skills,
            }
            for q in bank_questions
        ], indent=2)
        
        # Build candidate context
        resume_summary = self._build_resume_summary(resume)
        experience_level = self._infer_experience_level(resume)
        
        prompt = BATCH_ENHANCE_QUESTIONS_PROMPT.format(
            questions_json=questions_json,
            role_title=jd.title or "Software Engineer",
            experience_level=experience_level,
            candidate_skills=", ".join(resume.skills[:15]) if resume.skills else "Not specified",
            background_summary=resume_summary,
        )
        
        messages = [
            system_message(INTERVIEWER_SYSTEM_PROMPT),
            user_message(prompt),
        ]
        
        try:
            response = await self.llm.generate(
                messages,
                GenerationConfig(max_tokens=2048, temperature=0.6)
            )
            
            enhanced_data = self._parse_llm_json_response(response.content)
            
            # Build lookup map for bank questions
            bank_map = {q.id: q for q in bank_questions}
            
            # Process enhanced questions
            result = []
            for item in enhanced_data:
                original_id = item.get("original_id", "")
                enhanced_text = item.get("enhanced_question", "")
                personalized = item.get("personalization_applied", False)
                
                # Find original bank question
                bank_q = bank_map.get(original_id)
                if not bank_q:
                    # Try matching by index if ID not found
                    idx = enhanced_data.index(item)
                    if idx < len(bank_questions):
                        bank_q = bank_questions[idx]
                
                if bank_q and enhanced_text:
                    source = (
                        QuestionSource.BANK_PERSONALIZED
                        if personalized
                        else QuestionSource.BANK_REPHRASED
                    )
                    
                    result.append(GeneratedQuestion(
                        question=enhanced_text,
                        stage=self._map_stage_hint_to_stage(bank_q.stage_hint),
                        difficulty=QuestionDifficulty(bank_q.difficulty.value),
                        category=bank_q.category.value,
                        purpose=f"Evaluate {', '.join(bank_q.skills[:3])} skills",
                        expected_answer_points=[],
                        follow_up_questions=[],
                        duration_seconds=120,
                        source=source,
                        original_bank_question=bank_q.question_text,
                    ))
            
            # If batch failed partially, fill with originals
            if len(result) < len(bank_questions):
                processed_ids = {r.original_bank_question for r in result}
                for bank_q in bank_questions:
                    if bank_q.question_text not in processed_ids:
                        result.append(
                            self._bank_question_to_generated(bank_q, QuestionSource.BANK)
                        )
            
            return result
            
        except Exception as e:
            logger.error(f"Batch enhancement failed: {e}. Falling back to individual.")
            # Fallback: return original questions
            return [
                self._bank_question_to_generated(q, QuestionSource.BANK)
                for q in bank_questions
            ]
    
    async def _generate_gap_questions(
        self,
        uncovered_skills: List[str],
        resume: ParsedResume,
        jd: ParsedJobDescription,
        stage: InterviewStage,
        difficulty: QuestionDifficulty,
        count: int,
        example_questions: List[str],
        previous_questions: Optional[List[str]] = None,
    ) -> List[GeneratedQuestion]:
        """
        Generate questions for skills not covered by the bank.
        
        Args:
            uncovered_skills: Skills that need questions generated
            resume: Parsed candidate resume
            jd: Parsed job description
            stage: Interview stage
            difficulty: Target difficulty
            count: Number of questions to generate
            example_questions: Example questions from bank for style matching
            previous_questions: Questions to avoid
            
        Returns:
            List of generated gap-filling questions
        """
        if not uncovered_skills or count <= 0:
            return []
        
        resume_summary = self._build_resume_summary(resume)
        jd_summary = self._build_jd_summary(jd)
        
        prompt = GAP_FILLING_QUESTION_PROMPT.format(
            uncovered_skills=", ".join(uncovered_skills[:10]),
            stage=stage.value,
            difficulty=difficulty.value,
            count=count,
            resume_summary=resume_summary,
            jd_requirements=jd_summary,
            example_questions="\n".join(f"- {q}" for q in example_questions[:5]),
        )
        
        # Add exclusions if any
        if previous_questions:
            prompt += f"\n\nAvoid questions similar to these already asked:\n"
            for q in previous_questions[:10]:
                prompt += f"- {q}\n"
        
        messages = [
            system_message(INTERVIEWER_SYSTEM_PROMPT),
            user_message(prompt),
        ]
        
        try:
            response = await self.llm.generate(messages, self._generation_config)
            questions_data = self._parse_llm_json_response(response.content)
            
            questions = []
            for q_data in questions_data:
                if isinstance(q_data, dict) and "question" in q_data:
                    questions.append(GeneratedQuestion(
                        question=q_data["question"],
                        stage=stage,
                        difficulty=QuestionDifficulty(q_data.get("difficulty", difficulty.value)),
                        category=q_data.get("category", "general"),
                        purpose=q_data.get("purpose", f"Evaluate {q_data.get('skill', 'technical')} skills"),
                        expected_answer_points=q_data.get("expected_answer_points", []),
                        follow_up_questions=[],
                        duration_seconds=q_data.get("duration_seconds", 120),
                        source=QuestionSource.GENERATED,
                        original_bank_question=None,
                    ))
            
            logger.info(f"Generated {len(questions)} gap-filling questions for skills: {uncovered_skills[:5]}")
            return questions[:count]
            
        except Exception as e:
            logger.error(f"Failed to generate gap-filling questions: {e}")
            return []
    
    def _bank_question_to_generated(
        self,
        bank_q: BankQuestion,
        source: QuestionSource,
    ) -> GeneratedQuestion:
        """Convert a bank question to GeneratedQuestion format."""
        return GeneratedQuestion(
            question=bank_q.question_text,
            stage=self._map_stage_hint_to_stage(bank_q.stage_hint),
            difficulty=QuestionDifficulty(bank_q.difficulty.value),
            category=bank_q.category.value,
            purpose=f"Evaluate {', '.join(bank_q.skills[:3])} skills" if bank_q.skills else "Technical assessment",
            expected_answer_points=[],
            follow_up_questions=[],
            duration_seconds=120,
            source=source,
            original_bank_question=bank_q.question_text,
        )
    
    def _map_stage_hint_to_stage(self, hint: InterviewStageHint) -> InterviewStage:
        """Map question bank stage hint to interview stage."""
        mapping = {
            InterviewStageHint.SCREENING: InterviewStage.SCREENING,
            InterviewStageHint.TECHNICAL: InterviewStage.TECHNICAL,
            InterviewStageHint.BEHAVIORAL: InterviewStage.BEHAVIORAL,
            InterviewStageHint.SYSTEM_DESIGN: InterviewStage.SYSTEM_DESIGN,
            InterviewStageHint.GENERAL: InterviewStage.TECHNICAL,  # Default to technical
        }
        return mapping.get(hint, InterviewStage.TECHNICAL)
    
    def _find_relevant_experience(
        self,
        resume: ParsedResume,
        skills: List[str],
    ) -> Optional[str]:
        """Find resume experience relevant to the question skills."""
        if not skills or not resume.experience:
            return None
        
        skills_lower = {s.lower() for s in skills}
        
        for exp in resume.experience:
            try:
                # Handle both Experience objects and dicts
                if isinstance(exp, dict):
                    description = exp.get("description", "")
                    title = exp.get("title") or "Role"
                    company = exp.get("company") or "Company"
                else:
                    description = exp.description or ""
                    title = exp.title or "Role"
                    company = exp.company or "Company"
                
                if not description:
                    continue
                
                desc_lower = description.lower()
                matches = sum(1 for s in skills_lower if s in desc_lower)
                
                if matches >= 1:
                    return f"{title} at {company}: {description[:200]}"
            except Exception as e:
                logger.warning(f"Error processing experience entry: {e}")
                continue
        
        return None
    
    def _infer_experience_level(self, resume: ParsedResume) -> str:
        """Infer experience level from resume.
        
        Since start_date and end_date are strings (not datetime objects),
        we use the number of roles as a proxy for experience level.
        """
        if not resume.experience:
            return "entry-level"
        
        # Use number of roles as primary indicator since dates are strings
        num_roles = len(resume.experience)
        
        # Check for senior keywords in titles
        senior_keywords = {"senior", "lead", "principal", "staff", "director", "manager", "head", "vp", "chief"}
        has_senior_title = any(
            any(kw in (exp.title or "").lower() for kw in senior_keywords)
            for exp in resume.experience
        )
        
        if has_senior_title or num_roles >= 4:
            return "senior"
        elif num_roles >= 2:
            return "mid-level"
        else:
            return "entry-level"


# Global instance (lazy loaded)
_question_generator: Optional[QuestionGenerator] = None


def get_question_generator() -> QuestionGenerator:
    """Get or create the question generator instance."""
    global _question_generator
    if _question_generator is None:
        _question_generator = QuestionGenerator()
    return _question_generator
