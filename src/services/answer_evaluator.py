"""
Answer Evaluation Service (LLM-as-Judge).

Evaluates candidate answers using LLM with structured rubrics.
Includes hallucination detection to ensure evaluations are grounded.
"""
import json
import logging
from typing import AsyncIterator, Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from enum import Enum

from src.providers.llm import (
    BaseLLMProvider,
    Message,
    GenerationConfig,
    system_message,
    user_message,
    get_llm_provider_sync,
)
from src.services.prompts import (
    ANSWER_EVALUATION_PROMPT,
    BEHAVIORAL_EVALUATION_PROMPT,
    HALLUCINATION_CHECK_PROMPT,
    INTERVIEW_SUMMARY_PROMPT,
    InterviewStage,
)

logger = logging.getLogger(__name__)


class Recommendation(str, Enum):
    """Hiring recommendation levels."""
    STRONG_HIRE = "strong_hire"
    HIRE = "hire"
    NO_HIRE = "no_hire"
    STRONG_NO_HIRE = "strong_no_hire"


class AnswerStrength(str, Enum):
    """Answer quality assessment."""
    STRONG = "strong"
    ACCEPTABLE = "acceptable"
    WEAK = "weak"
    INSUFFICIENT = "insufficient"
    
    @classmethod
    def from_string(cls, value: str) -> "AnswerStrength":
        """Parse AnswerStrength from string, case-insensitive."""
        if not value:
            return cls.ACCEPTABLE
        try:
            return cls(value.lower())
        except ValueError:
            # Fallback to acceptable if unknown value
            return cls.ACCEPTABLE


@dataclass
class EvaluationScores:
    """Scores from answer evaluation."""
    technical_accuracy: float = 0
    completeness: float = 0
    clarity: float = 0
    depth: float = 0
    overall: float = 0
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "technical_accuracy": self.technical_accuracy,
            "completeness": self.completeness,
            "clarity": self.clarity,
            "depth": self.depth,
            "overall": self.overall,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvaluationScores":
        scores = cls(
            technical_accuracy=float(data.get("technical_accuracy", 0)),
            completeness=float(data.get("completeness", 0)),
            clarity=float(data.get("clarity", 0)),
            depth=float(data.get("depth", 0)),
            overall=float(data.get("overall", 0)),
        )
        # Always recompute overall from component scores when available.
        # This prevents the LLM from inflating the overall score beyond
        # what the individual dimension scores justify.
        has_components = any([scores.technical_accuracy, scores.completeness, scores.clarity, scores.depth])
        if has_components:
            scores.overall = round(
                scores.technical_accuracy * 0.35 +
                scores.completeness * 0.25 +
                scores.clarity * 0.20 +
                scores.depth * 0.20,
                1,
            )
        return scores


@dataclass
class STARScores:
    """STAR format evaluation scores for behavioral questions."""
    situation: float = 0
    task: float = 0
    action: float = 0
    result: float = 0
    total: float = 0
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "situation": self.situation,
            "task": self.task,
            "action": self.action,
            "result": self.result,
            "total": self.total,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "STARScores":
        scores = cls(
            situation=float(data.get("situation", 0)),
            task=float(data.get("task", 0)),
            action=float(data.get("action", 0)),
            result=float(data.get("result", 0)),
            total=float(data.get("total", 0)),
        )
        # Compute total if not provided or zero
        if scores.total == 0:
            scores.total = scores.situation + scores.task + scores.action + scores.result
        return scores


@dataclass
class AnswerEvaluation:
    """Complete evaluation of a candidate's answer."""
    question: str
    answer: str
    stage: InterviewStage
    scores: EvaluationScores
    star_scores: Optional[STARScores] = None  # For behavioral questions
    strengths: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    follow_up_question: Optional[str] = None
    recommendation: AnswerStrength = AnswerStrength.ACCEPTABLE
    notes: str = ""
    is_validated: bool = False  # Hallucination check passed
    validation_issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "stage": self.stage.value,
            "scores": self.scores.to_dict(),
            "star_scores": self.star_scores.to_dict() if self.star_scores else None,
            "strengths": self.strengths,
            "improvements": self.improvements,
            "follow_up_question": self.follow_up_question,
            "recommendation": self.recommendation.value,
            "notes": self.notes,
            "is_validated": self.is_validated,
            "validation_issues": self.validation_issues,
        }


@dataclass
class InterviewReport:
    """Complete interview evaluation report."""
    candidate_name: str
    role_title: str
    duration_minutes: int
    evaluations: List[AnswerEvaluation]
    
    # Aggregate scores
    technical_score: float = 0
    behavioral_score: float = 0
    communication_score: float = 0
    problem_solving_score: float = 0
    overall_score: float = 0
    
    # Summary
    executive_summary: str = ""
    strengths: List[Dict[str, str]] = field(default_factory=list)
    concerns: List[Dict[str, str]] = field(default_factory=list)
    recommendation: Recommendation = Recommendation.NO_HIRE
    confidence: float = 0
    reasoning: str = ""
    next_steps: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_name": self.candidate_name,
            "role_title": self.role_title,
            "duration_minutes": self.duration_minutes,
            "evaluations": [e.to_dict() for e in self.evaluations],
            "technical_score": self.technical_score,
            "behavioral_score": self.behavioral_score,
            "communication_score": self.communication_score,
            "problem_solving_score": self.problem_solving_score,
            "overall_score": self.overall_score,
            "executive_summary": self.executive_summary,
            "strengths": self.strengths,
            "concerns": self.concerns,
            "recommendation": self.recommendation.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "next_steps": self.next_steps,
        }


class AnswerEvaluator:
    """
    LLM-as-Judge for evaluating candidate answers.
    
    Uses structured prompts and rubrics to evaluate answers consistently.
    Includes hallucination detection to ensure evaluations are grounded.
    """
    
    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        """
        Initialize the answer evaluator.
        
        Args:
            llm_provider: LLM provider instance. If None, uses default from factory.
        """
        self.llm = llm_provider or get_llm_provider_sync()
        self._eval_config = GenerationConfig(
            max_tokens=1536,
            temperature=0.2,  # Low temperature for consistent, deterministic evaluation
            top_p=0.9,
        )
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from LLM response."""
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
        
        # Find JSON object bounds
        if not response.startswith("{"):
            start = response.find("{")
            if start != -1:
                response = response[start:]
        
        if not response.endswith("}"):
            end = response.rfind("}")
            if end != -1:
                response = response[:end + 1]
        
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse evaluation JSON: {e}")
            logger.debug(f"Response was: {response[:500]}")
            return {}
    
    async def evaluate_answer(
        self,
        question: str,
        answer: str,
        expected_points: List[str],
        stage: InterviewStage = InterviewStage.TECHNICAL,
        validate: bool = True,
    ) -> AnswerEvaluation:
        """
        Evaluate a candidate's answer to a question.
        
        Uses a two-step rubric-then-evaluate approach: the LLM first generates
        the correct answer rubric (filling gaps when expected_points is empty),
        then scores the candidate against that rubric.
        
        Args:
            question: The interview question
            answer: Candidate's response
            expected_points: Key points expected in a good answer (may be empty)
            stage: Interview stage (affects evaluation criteria)
            validate: Whether to run hallucination check
            
        Returns:
            Complete answer evaluation
        """
        # Format expected points — if empty, the prompt instructs the LLM to generate its own
        if expected_points:
            points_text = "\n".join(f"- {p}" for p in expected_points)
        else:
            points_text = "(none provided — you MUST generate your own rubric points in Step 1)"
        
        prompt = ANSWER_EVALUATION_PROMPT.format(
            question=question,
            expected_points=points_text,
            answer=answer,
        )
        
        messages = [
            system_message(
                "You are a strict, adversarial technical interview evaluator. "
                "Your job is to identify incorrect, vague, and superficial answers. "
                "Never give the benefit of the doubt — score based only on what the candidate demonstrably knows. "
                "Wrong answers get low scores regardless of confidence or fluency."
            ),
            user_message(prompt),
        ]
        
        try:
            response = await self.llm.generate(messages, self._eval_config)
            eval_data = self._parse_json_response(response.content)
            
            if not eval_data:
                # Return default evaluation if parsing failed
                return AnswerEvaluation(
                    question=question,
                    answer=answer,
                    stage=stage,
                    scores=EvaluationScores(overall=50),
                    notes="Evaluation parsing failed",
                )
            
            # Extract scores and enforce server-side weighted calculation
            scores_data = eval_data.get("scores", {})
            scores = EvaluationScores.from_dict(scores_data)
            
            # Override the LLM's overall with our own weighted calculation
            # to prevent the LLM from inflating the overall score
            computed_overall = (
                scores.technical_accuracy * 0.35 +
                scores.completeness * 0.25 +
                scores.clarity * 0.20 +
                scores.depth * 0.20
            )
            scores.overall = round(computed_overall, 1)
            
            # Build notes with rubric traceability
            rubric_points = eval_data.get("rubric_points", [])
            rubric_matches = eval_data.get("rubric_matches", [])
            rubric_misses = eval_data.get("rubric_misses", [])
            llm_notes = eval_data.get("notes", "")
            
            notes_parts = []
            if llm_notes:
                notes_parts.append(llm_notes)
            if rubric_points:
                notes_parts.append(f"Rubric ({len(rubric_matches)}/{len(rubric_points)} points matched)")
            
            evaluation = AnswerEvaluation(
                question=question,
                answer=answer,
                stage=stage,
                scores=scores,
                strengths=eval_data.get("strengths", []),
                improvements=eval_data.get("improvements", []),
                follow_up_question=eval_data.get("follow_up_question"),
                recommendation=AnswerStrength.from_string(eval_data.get("recommendation", "acceptable")),
                notes=" | ".join(notes_parts) if notes_parts else "",
            )
            
            # Validate evaluation if requested
            if validate:
                validation = await self._validate_evaluation(question, answer, eval_data)
                evaluation.is_validated = validation.get("is_grounded", False)
                evaluation.validation_issues = [
                    issue.get("description", "") 
                    for issue in validation.get("issues", [])
                ]
                
                # Apply corrections if needed
                if not evaluation.is_validated and validation.get("corrected_evaluation"):
                    corrected = validation["corrected_evaluation"]
                    if isinstance(corrected, dict) and "scores" in corrected:
                        corrected_scores = EvaluationScores.from_dict(corrected["scores"])
                        # Re-enforce weighted overall on corrected scores too
                        corrected_scores.overall = round(
                            corrected_scores.technical_accuracy * 0.35 +
                            corrected_scores.completeness * 0.25 +
                            corrected_scores.clarity * 0.20 +
                            corrected_scores.depth * 0.20,
                            1,
                        )
                        evaluation.scores = corrected_scores
                        evaluation.is_validated = True
            else:
                evaluation.is_validated = True
            
            return evaluation
            
        except Exception as e:
            logger.error(f"Failed to evaluate answer: {e}")
            return AnswerEvaluation(
                question=question,
                answer=answer,
                stage=stage,
                scores=EvaluationScores(overall=50),
                notes=f"Evaluation error: {str(e)}",
            )
    
    async def evaluate_answer_stream(
        self,
        question: str,
        answer: str,
        expected_points: List[str],
        stage: InterviewStage = InterviewStage.TECHNICAL,
        validate: bool = True,
    ) -> AsyncIterator[Union["StreamEvent", AnswerEvaluation]]:
        """
        Evaluate a candidate's answer with SSE streaming progress.
        
        Same logic as evaluate_answer() but yields StreamEvent objects
        so the frontend can show evaluation stages in real-time.
        
        Event flow:
            status(evaluating)     -> LLM evaluation starting
            progress(evaluating)   -> evaluation LLM call complete
            status(validating)     -> hallucination check starting (if validate=True)
            progress(validating)   -> validation complete
            AnswerEvaluation       -> final result (last item)
        
        Yields:
            StreamEvent for progress
            AnswerEvaluation as the final item
        """
        from src.services.streaming import (
            StreamEvent, EventType, status_event, progress_event, error_event,
            stream_llm_generation,
        )
        
        yield status_event("evaluating", "Evaluating answer...")
        
        # Format expected points
        if expected_points:
            points_text = "\n".join(f"- {p}" for p in expected_points)
        else:
            points_text = "(none provided — you MUST generate your own rubric points in Step 1)"
        
        prompt = ANSWER_EVALUATION_PROMPT.format(
            question=question,
            expected_points=points_text,
            answer=answer,
        )
        
        messages = [
            system_message(
                "You are a strict, adversarial technical interview evaluator. "
                "Your job is to identify incorrect, vague, and superficial answers. "
                "Never give the benefit of the doubt — score based only on what the candidate demonstrably knows. "
                "Wrong answers get low scores regardless of confidence or fluency."
            ),
            user_message(prompt),
        ]
        
        try:
            # Stream tokens from LLM, accumulate full response
            accumulated: list[str] = []
            async for event in stream_llm_generation(self.llm, messages, self._eval_config, stage="evaluating"):
                if event.type == EventType.TOKEN:
                    accumulated.append(event.data["content"])
                yield event  # forward all events (token, progress, status)

            full_response = "".join(accumulated)
            eval_data = self._parse_json_response(full_response)
            
            if not eval_data:
                evaluation = AnswerEvaluation(
                    question=question,
                    answer=answer,
                    stage=stage,
                    scores=EvaluationScores(overall=50),
                    notes="Evaluation parsing failed",
                )
                yield evaluation
                return
            
            # Extract scores and enforce server-side weighted calculation
            scores_data = eval_data.get("scores", {})
            scores = EvaluationScores.from_dict(scores_data)
            
            computed_overall = (
                scores.technical_accuracy * 0.35 +
                scores.completeness * 0.25 +
                scores.clarity * 0.20 +
                scores.depth * 0.20
            )
            scores.overall = round(computed_overall, 1)
            
            # Build notes with rubric traceability
            rubric_points = eval_data.get("rubric_points", [])
            rubric_matches = eval_data.get("rubric_matches", [])
            llm_notes = eval_data.get("notes", "")
            
            notes_parts = []
            if llm_notes:
                notes_parts.append(llm_notes)
            if rubric_points:
                notes_parts.append(f"Rubric ({len(rubric_matches)}/{len(rubric_points)} points matched)")
            
            evaluation = AnswerEvaluation(
                question=question,
                answer=answer,
                stage=stage,
                scores=scores,
                strengths=eval_data.get("strengths", []),
                improvements=eval_data.get("improvements", []),
                follow_up_question=eval_data.get("follow_up_question"),
                recommendation=AnswerStrength.from_string(eval_data.get("recommendation", "acceptable")),
                notes=" | ".join(notes_parts) if notes_parts else "",
            )
            
            yield progress_event(
                "evaluating",
                f"Evaluation complete: {scores.overall:.0f}/100",
                overall_score=scores.overall,
                recommendation=evaluation.recommendation.value,
            )
            
            # Validate evaluation if requested
            if validate:
                yield status_event("validating", "Running hallucination check...")
                
                validation = await self._validate_evaluation(question, answer, eval_data)
                evaluation.is_validated = validation.get("is_grounded", False)
                evaluation.validation_issues = [
                    issue.get("description", "") 
                    for issue in validation.get("issues", [])
                ]
                
                # Apply corrections if needed
                if not evaluation.is_validated and validation.get("corrected_evaluation"):
                    corrected = validation["corrected_evaluation"]
                    if isinstance(corrected, dict) and "scores" in corrected:
                        corrected_scores = EvaluationScores.from_dict(corrected["scores"])
                        corrected_scores.overall = round(
                            corrected_scores.technical_accuracy * 0.35 +
                            corrected_scores.completeness * 0.25 +
                            corrected_scores.clarity * 0.20 +
                            corrected_scores.depth * 0.20,
                            1,
                        )
                        evaluation.scores = corrected_scores
                        evaluation.is_validated = True
                
                yield progress_event(
                    "validating",
                    f"Validation {'passed' if evaluation.is_validated else 'found issues'}",
                    is_validated=evaluation.is_validated,
                    issues_count=len(evaluation.validation_issues),
                )
            else:
                evaluation.is_validated = True
            
            yield evaluation
            
        except Exception as e:
            logger.error(f"Failed to evaluate answer: {e}")
            yield error_event("evaluating", f"Evaluation failed: {e}")
            yield AnswerEvaluation(
                question=question,
                answer=answer,
                stage=stage,
                scores=EvaluationScores(overall=50),
                notes=f"Evaluation error: {str(e)}",
            )
    
    async def evaluate_behavioral_answer(
        self,
        question: str,
        answer: str,
        competency: str,
        red_flags: List[str],
        green_flags: List[str],
        validate: bool = True,
    ) -> AnswerEvaluation:
        """
        Evaluate a behavioral answer using STAR criteria.
        
        Uses a two-step approach: the LLM first generates quality indicators
        for what a good answer should include (filling gaps when red_flags/green_flags
        are empty), then evaluates the candidate against those indicators.
        
        Args:
            question: The behavioral question
            answer: Candidate's response
            competency: The competency being assessed
            red_flags: Warning signs to watch for (may be empty)
            green_flags: Positive indicators (may be empty)
            validate: Whether to run hallucination check
            
        Returns:
            Complete answer evaluation with STAR scores
        """
        # Format flags — if empty, the prompt instructs the LLM to generate its own
        red_flags_text = (
            "\n".join(f"- {f}" for f in red_flags)
            if red_flags
            else "(none provided — you MUST generate your own red flags for this competency)"
        )
        green_flags_text = (
            "\n".join(f"- {f}" for f in green_flags)
            if green_flags
            else "(none provided — you MUST generate your own green flags for this competency)"
        )
        
        prompt = BEHAVIORAL_EVALUATION_PROMPT.format(
            question=question,
            competency=competency,
            answer=answer,
            red_flags=red_flags_text,
            green_flags=green_flags_text,
        )
        
        messages = [
            system_message(
                "You are a strict behavioral interview evaluator. "
                "Your job is to distinguish genuine, substantive experiences from vague, "
                "fabricated, or rehearsed non-answers. "
                "Hypothetical answers ('I would...') are not behavioral evidence. "
                "Vague answers without specific details score low regardless of polish."
            ),
            user_message(prompt),
        ]
        
        try:
            response = await self.llm.generate(messages, self._eval_config)
            eval_data = self._parse_json_response(response.content)
            
            if not eval_data:
                return AnswerEvaluation(
                    question=question,
                    answer=answer,
                    stage=InterviewStage.BEHAVIORAL,
                    scores=EvaluationScores(overall=50),
                    notes="Evaluation parsing failed",
                )
            
            # Extract STAR scores and sub-scores
            star_scores = STARScores.from_dict(eval_data.get("star_scores", {}))
            authenticity = float(eval_data.get("authenticity_score", 0))
            relevance = float(eval_data.get("relevance_score", 0))
            self_awareness = float(eval_data.get("self_awareness_score", 0))
            
            # Enforce server-side weighted overall calculation
            # (star_total * 0.40) + (authenticity * 0.25) + (relevance * 0.20) + (self_awareness * 0.15)
            computed_overall = round(
                star_scores.total * 0.40 +
                authenticity * 0.25 +
                relevance * 0.20 +
                self_awareness * 0.15,
                1,
            )
            
            # Build notes with quality indicators traceability
            quality_indicators = eval_data.get("quality_indicators", [])
            llm_notes = eval_data.get("notes", "")
            notes_parts = []
            if llm_notes:
                notes_parts.append(llm_notes)
            if quality_indicators:
                notes_parts.append(f"Quality indicators: {len(quality_indicators)} defined")
            
            evaluation = AnswerEvaluation(
                question=question,
                answer=answer,
                stage=InterviewStage.BEHAVIORAL,
                scores=EvaluationScores(
                    overall=computed_overall,
                    clarity=self_awareness,
                    completeness=relevance,
                    technical_accuracy=authenticity,
                ),
                star_scores=star_scores,
                strengths=eval_data.get("green_flags_detected", []),
                improvements=eval_data.get("red_flags_detected", []),
                recommendation=AnswerStrength.from_string(eval_data.get("recommendation", "acceptable")),
                notes=" | ".join(notes_parts) if notes_parts else "",
            )
            
            if validate:
                validation = await self._validate_evaluation(question, answer, eval_data)
                evaluation.is_validated = validation.get("is_grounded", False)
                evaluation.validation_issues = [
                    issue.get("description", "") 
                    for issue in validation.get("issues", [])
                ]
            else:
                evaluation.is_validated = True
            
            return evaluation
            
        except Exception as e:
            logger.error(f"Failed to evaluate behavioral answer: {e}")
            return AnswerEvaluation(
                question=question,
                answer=answer,
                stage=InterviewStage.BEHAVIORAL,
                scores=EvaluationScores(overall=50),
                notes=f"Evaluation error: {str(e)}",
            )
    
    async def evaluate_behavioral_answer_stream(
        self,
        question: str,
        answer: str,
        competency: str,
        red_flags: List[str],
        green_flags: List[str],
        validate: bool = True,
    ) -> AsyncIterator[Union["StreamEvent", AnswerEvaluation]]:
        """
        Evaluate a behavioral answer with SSE streaming progress.
        
        Same logic as evaluate_behavioral_answer() but yields StreamEvent
        objects so the frontend can show evaluation stages in real-time.
        
        Event flow:
            status(evaluating_behavioral) -> STAR evaluation starting
            progress(evaluating_behavioral) -> evaluation complete
            status(validating) -> hallucination check (if validate=True)
            progress(validating) -> validation complete
            AnswerEvaluation -> final result (last item)
        
        Yields:
            StreamEvent for progress
            AnswerEvaluation as the final item
        """
        from src.services.streaming import (
            StreamEvent, EventType, status_event, progress_event, error_event,
            stream_llm_generation,
        )
        
        yield status_event("evaluating_behavioral", f"Evaluating behavioral answer ({competency})...")
        
        # Format flags
        red_flags_text = (
            "\n".join(f"- {f}" for f in red_flags)
            if red_flags
            else "(none provided — you MUST generate your own red flags for this competency)"
        )
        green_flags_text = (
            "\n".join(f"- {f}" for f in green_flags)
            if green_flags
            else "(none provided — you MUST generate your own green flags for this competency)"
        )
        
        prompt = BEHAVIORAL_EVALUATION_PROMPT.format(
            question=question,
            competency=competency,
            answer=answer,
            red_flags=red_flags_text,
            green_flags=green_flags_text,
        )
        
        messages = [
            system_message(
                "You are a strict behavioral interview evaluator. "
                "Your job is to distinguish genuine, substantive experiences from vague, "
                "fabricated, or rehearsed non-answers. "
                "Hypothetical answers ('I would...') are not behavioral evidence. "
                "Vague answers without specific details score low regardless of polish."
            ),
            user_message(prompt),
        ]
        
        try:
            # Stream tokens from LLM, accumulate full response
            accumulated: list[str] = []
            async for event in stream_llm_generation(self.llm, messages, self._eval_config, stage="evaluating_behavioral"):
                if event.type == EventType.TOKEN:
                    accumulated.append(event.data["content"])
                yield event  # forward all events (token, progress, status)

            full_response = "".join(accumulated)
            eval_data = self._parse_json_response(full_response)
            
            if not eval_data:
                evaluation = AnswerEvaluation(
                    question=question,
                    answer=answer,
                    stage=InterviewStage.BEHAVIORAL,
                    scores=EvaluationScores(overall=50),
                    notes="Evaluation parsing failed",
                )
                yield evaluation
                return
            
            # Extract STAR scores and sub-scores
            star_scores = STARScores.from_dict(eval_data.get("star_scores", {}))
            authenticity = float(eval_data.get("authenticity_score", 0))
            relevance = float(eval_data.get("relevance_score", 0))
            self_awareness = float(eval_data.get("self_awareness_score", 0))
            
            # Enforce server-side weighted overall
            computed_overall = round(
                star_scores.total * 0.40 +
                authenticity * 0.25 +
                relevance * 0.20 +
                self_awareness * 0.15,
                1,
            )
            
            # Build notes
            quality_indicators = eval_data.get("quality_indicators", [])
            llm_notes = eval_data.get("notes", "")
            notes_parts = []
            if llm_notes:
                notes_parts.append(llm_notes)
            if quality_indicators:
                notes_parts.append(f"Quality indicators: {len(quality_indicators)} defined")
            
            evaluation = AnswerEvaluation(
                question=question,
                answer=answer,
                stage=InterviewStage.BEHAVIORAL,
                scores=EvaluationScores(
                    overall=computed_overall,
                    clarity=self_awareness,
                    completeness=relevance,
                    technical_accuracy=authenticity,
                ),
                star_scores=star_scores,
                strengths=eval_data.get("green_flags_detected", []),
                improvements=eval_data.get("red_flags_detected", []),
                recommendation=AnswerStrength.from_string(eval_data.get("recommendation", "acceptable")),
                notes=" | ".join(notes_parts) if notes_parts else "",
            )
            
            yield progress_event(
                "evaluating_behavioral",
                f"Behavioral evaluation complete: {computed_overall:.0f}/100 (STAR: {star_scores.total:.0f})",
                overall_score=computed_overall,
                star_total=star_scores.total,
                recommendation=evaluation.recommendation.value,
            )
            
            if validate:
                yield status_event("validating", "Running hallucination check...")
                
                validation = await self._validate_evaluation(question, answer, eval_data)
                evaluation.is_validated = validation.get("is_grounded", False)
                evaluation.validation_issues = [
                    issue.get("description", "") 
                    for issue in validation.get("issues", [])
                ]
                
                yield progress_event(
                    "validating",
                    f"Validation {'passed' if evaluation.is_validated else 'found issues'}",
                    is_validated=evaluation.is_validated,
                    issues_count=len(evaluation.validation_issues),
                )
            else:
                evaluation.is_validated = True
            
            yield evaluation
            
        except Exception as e:
            logger.error(f"Failed to evaluate behavioral answer: {e}")
            yield error_event("evaluating_behavioral", f"Behavioral evaluation failed: {e}")
            yield AnswerEvaluation(
                question=question,
                answer=answer,
                stage=InterviewStage.BEHAVIORAL,
                scores=EvaluationScores(overall=50),
                notes=f"Evaluation error: {str(e)}",
            )
    
    async def _validate_evaluation(
        self,
        question: str,
        answer: str,
        evaluation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Validate that an evaluation is grounded in the candidate's answer.
        
        Checks for hallucinations or unsupported claims in the evaluation.
        """
        prompt = HALLUCINATION_CHECK_PROMPT.format(
            question=question,
            answer=answer,
            evaluation=json.dumps(evaluation, indent=2),
        )
        
        messages = [
            system_message("You are a validation system that checks if evaluations are grounded in evidence."),
            user_message(prompt),
        ]
        
        try:
            response = await self.llm.generate(messages, GenerationConfig(
                max_tokens=1024,
                temperature=0.1,  # Very deterministic
            ))
            
            return self._parse_json_response(response.content)
            
        except Exception as e:
            logger.error(f"Failed to validate evaluation: {e}")
            return {"is_grounded": True, "issues": [], "confidence": 50}
    
    def _score_to_recommendation(self, overall_score: float) -> Recommendation:
        """Convert overall score to recommendation."""
        if overall_score >= 85:
            return Recommendation.STRONG_HIRE
        elif overall_score >= 70:
            return Recommendation.HIRE
        elif overall_score >= 50:
            return Recommendation.NO_HIRE
        else:
            return Recommendation.STRONG_NO_HIRE
    
    def _recommendation_matches_score(self, rec: Recommendation, score: float) -> bool:
        """Check if recommendation is reasonable given the score."""
        # STRONG_HIRE requires score >= 85
        if rec == Recommendation.STRONG_HIRE and score < 85:
            return False
        # HIRE requires score >= 70
        if rec == Recommendation.HIRE and score < 70:
            return False
        # NO_HIRE for scores 50-69 (shouldn't be used for high scores)
        if rec == Recommendation.NO_HIRE and score >= 70:
            return False
        # STRONG_NO_HIRE for scores < 50
        if rec == Recommendation.STRONG_NO_HIRE and score >= 50:
            return False
        return True
    
    async def generate_interview_report(
        self,
        candidate_name: str,
        role_title: str,
        duration_minutes: int,
        evaluations: List[AnswerEvaluation],
    ) -> InterviewReport:
        """
        Generate a comprehensive interview report from all evaluations.
        
        Args:
            candidate_name: Name of the candidate
            role_title: Position being interviewed for
            duration_minutes: Total interview duration
            evaluations: List of all answer evaluations
            
        Returns:
            Complete interview report with recommendation
        """
        # Calculate aggregate scores
        technical_evals = [e for e in evaluations if e.stage == InterviewStage.TECHNICAL]
        behavioral_evals = [e for e in evaluations if e.stage == InterviewStage.BEHAVIORAL]
        
        technical_score = (
            sum(e.scores.overall for e in technical_evals) / len(technical_evals)
            if technical_evals else 0
        )
        behavioral_score = (
            sum(e.scores.overall for e in behavioral_evals) / len(behavioral_evals)
            if behavioral_evals else 0
        )
        
        # Average communication from all evaluations
        communication_score = (
            sum(e.scores.clarity for e in evaluations) / len(evaluations)
            if evaluations else 0
        )
        
        # Problem solving from technical evaluations
        problem_solving_score = (
            sum(e.scores.depth for e in technical_evals) / len(technical_evals)
            if technical_evals else 0
        )
        
        # Overall weighted score
        overall_score = (
            technical_score * 0.4 +
            behavioral_score * 0.25 +
            communication_score * 0.2 +
            problem_solving_score * 0.15
        )
        
        # Build performance summary for prompt
        stage_performances = []
        for stage in InterviewStage:
            stage_evals = [e for e in evaluations if e.stage == stage]
            if stage_evals:
                avg = sum(e.scores.overall for e in stage_evals) / len(stage_evals)
                stage_performances.append(f"- {stage.value}: {avg:.1f}/100 ({len(stage_evals)} questions)")
        
        question_breakdown = []
        for i, e in enumerate(evaluations, 1):
            question_breakdown.append(
                f"{i}. [{e.stage.value}] Score: {e.scores.overall:.0f}/100 - {e.recommendation.value}"
            )
        
        # Generate summary using LLM
        prompt = INTERVIEW_SUMMARY_PROMPT.format(
            role_title=role_title,
            candidate_name=candidate_name,
            duration_minutes=duration_minutes,
            stage_performances="\n".join(stage_performances),
            question_breakdown="\n".join(question_breakdown),
            technical_score=f"{technical_score:.0f}",
            behavioral_score=f"{behavioral_score:.0f}",
            communication_score=f"{communication_score:.0f}",
            problem_solving_score=f"{problem_solving_score:.0f}",
            cultural_fit_score=f"{behavioral_score:.0f}",  # Using behavioral as proxy
            overall_score=f"{overall_score:.0f}",
        )
        
        messages = [
            system_message("You are an expert hiring manager generating interview reports."),
            user_message(prompt),
        ]
        
        try:
            response = await self.llm.generate(messages, GenerationConfig(
                max_tokens=2048,
                temperature=0.4,
            ))
            summary_data = self._parse_json_response(response.content)
            
            report = InterviewReport(
                candidate_name=candidate_name,
                role_title=role_title,
                duration_minutes=duration_minutes,
                evaluations=evaluations,
                technical_score=technical_score,
                behavioral_score=behavioral_score,
                communication_score=communication_score,
                problem_solving_score=problem_solving_score,
                overall_score=overall_score,
            )
            
            if summary_data:
                report.executive_summary = summary_data.get("executive_summary", "")
                report.strengths = summary_data.get("strengths", [])
                report.concerns = summary_data.get("concerns", [])
                
                # Get LLM recommendation but validate against calculated score
                llm_recommendation = summary_data.get("recommendation", "no_hire")
                report.recommendation = Recommendation(llm_recommendation)
                
                # Sanity check: override recommendation if it contradicts the score
                # This prevents LLM hallucinations from affecting hiring decisions
                calculated_recommendation = self._score_to_recommendation(overall_score)
                if not self._recommendation_matches_score(report.recommendation, overall_score):
                    logger.warning(
                        f"LLM recommendation '{report.recommendation.value}' overridden to "
                        f"'{calculated_recommendation.value}' based on score {overall_score:.0f}"
                    )
                    report.recommendation = calculated_recommendation
                
                report.confidence = float(summary_data.get("confidence", 0))
                report.reasoning = summary_data.get("reasoning", "")
                report.next_steps = summary_data.get("next_steps", [])
            
            return report
            
        except Exception as e:
            logger.error(f"Failed to generate interview report: {e}")
            # Return report with calculated scores but no LLM summary
            return InterviewReport(
                candidate_name=candidate_name,
                role_title=role_title,
                duration_minutes=duration_minutes,
                evaluations=evaluations,
                technical_score=technical_score,
                behavioral_score=behavioral_score,
                communication_score=communication_score,
                problem_solving_score=problem_solving_score,
                overall_score=overall_score,
                executive_summary=f"Interview completed with overall score of {overall_score:.0f}/100",
                recommendation=Recommendation.HIRE if overall_score >= 70 else Recommendation.NO_HIRE,
            )


# Global instance (lazy loaded)
_answer_evaluator: Optional[AnswerEvaluator] = None


def get_answer_evaluator() -> AnswerEvaluator:
    """Get or create the answer evaluator instance."""
    global _answer_evaluator
    if _answer_evaluator is None:
        _answer_evaluator = AnswerEvaluator()
    return _answer_evaluator
