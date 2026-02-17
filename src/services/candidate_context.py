"""
Candidate Context Builder for Question Augmentation (Phase 7).

After each candidate answer, builds and updates a structured "Candidate
Context Profile" that captures demonstrated skills, weak areas, standout
claims, and follow-up hooks.  This context is then used to:
    1. Augment the next pre-generated base question with conversational
       references to prior answers.
    2. Decide whether to insert a follow-up sub-question before moving on.

The context extraction uses a dedicated LLM call after each answer to
produce rich, nuanced insights that rule-based extraction cannot achieve.
"""
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from src.providers.llm import (
    BaseLLMProvider,
    GenerationConfig,
    get_llm_provider_sync,
    system_message,
    user_message,
)
from src.services.prompts import CONTEXT_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# "I don't know" detection — simple pattern matching, no LLM call
# ------------------------------------------------------------------

_DONT_KNOW_PATTERNS = [
    "i don't know",
    "i dont know",
    "i don't remember",
    "i dont remember",
    "i'm not sure",
    "im not sure",
    "no idea",
    "not sure",
    "i have no idea",
    "i can't answer",
    "i cannot answer",
    "i can't answer this",
    "i cannot answer this",
]

_DONT_KNOW_EXACT = {
    "(question skipped by candidate)",
    "(no answer provided - timer expired)",
}


def is_dont_know_answer(answer_text: str) -> bool:
    """Return True if the candidate effectively said 'I don't know' or gave up."""
    normalised = answer_text.strip().lower()
    if normalised in _DONT_KNOW_EXACT:
        return True
    for pattern in _DONT_KNOW_PATTERNS:
        if pattern in normalised:
            return True
    return False


@dataclass
class CandidateContext:
    """Structured profile of a candidate built incrementally during the interview."""

    resume_summary: str = ""
    jd_summary: str = ""
    match_summary: str = ""

    # Accumulated from LLM extractions
    qa_history: List[Dict[str, Any]] = field(default_factory=list)
    demonstrated_skills: List[str] = field(default_factory=list)
    weak_areas: List[str] = field(default_factory=list)
    standout_points: List[str] = field(default_factory=list)
    follow_up_hooks: List[str] = field(default_factory=list)
    cross_stage_connections: List[str] = field(default_factory=list)

    # Meta
    confidence_assessment: str = "medium"
    suggested_focus: str = ""
    current_stage: str = ""
    questions_remaining: int = 0

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateContext":
        if data is None:
            return cls()
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def to_prompt_section(self) -> str:
        """Serialise into a concise text block suitable for injection into LLM prompts."""
        lines: List[str] = []
        lines.append("=== Candidate Context Profile ===")

        if self.demonstrated_skills:
            lines.append(f"Demonstrated skills: {', '.join(self.demonstrated_skills)}")
        if self.weak_areas:
            lines.append(f"Weak areas: {', '.join(self.weak_areas)}")
        if self.standout_points:
            lines.append(f"Standout points: {'; '.join(self.standout_points)}")
        if self.follow_up_hooks:
            lines.append(f"Follow-up hooks: {'; '.join(self.follow_up_hooks)}")
        if self.cross_stage_connections:
            lines.append(f"Cross-stage connections: {'; '.join(self.cross_stage_connections)}")
        if self.suggested_focus:
            lines.append(f"Suggested next focus: {self.suggested_focus}")
        lines.append(f"Confidence in candidate: {self.confidence_assessment}")

        if self.qa_history:
            lines.append(f"\nQ&A history ({len(self.qa_history)} answers):")
            for i, qa in enumerate(self.qa_history, 1):
                score = qa.get("score", "?")
                lines.append(f"  Q{i} [{qa.get('stage', '?')}] (score {score}): {qa.get('question', '')[:120]}")
                answer_preview = qa.get("answer", "")[:150]
                lines.append(f"      A: {answer_preview}")

        lines.append("===")
        return "\n".join(lines)


class CandidateContextBuilder:
    """
    Builds and incrementally updates a CandidateContext using an LLM call
    after each answered question.
    """

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm = llm_provider or get_llm_provider_sync()
        self._config = GenerationConfig(
            max_tokens=1024,
            temperature=0.3,  # deterministic analysis
            top_p=0.9,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def update_context(
        self,
        existing_context: Optional[CandidateContext],
        *,
        role_title: str,
        resume_summary: str,
        match_summary: str,
        current_stage: str,
        questions_remaining: int,
        latest_question: str,
        latest_answer: str,
        latest_score: float,
        latest_recommendation: str,
        latest_strengths: List[str],
        latest_improvements: List[str],
        qa_history: List[Dict[str, Any]],
    ) -> CandidateContext:
        """
        Update the candidate context after a new answer has been evaluated.

        Makes a single LLM call to extract structured insights, then merges
        the results into the running context.

        Returns:
            Updated CandidateContext (never None).
        """
        ctx = existing_context or CandidateContext()
        ctx.resume_summary = resume_summary
        ctx.jd_summary = ""  # kept brief — the match summary covers this
        ctx.match_summary = match_summary
        ctx.current_stage = current_stage
        ctx.questions_remaining = questions_remaining
        ctx.qa_history = qa_history

        # Build the existing-context string for the prompt
        existing_context_str = ctx.to_prompt_section() if existing_context else "No prior context (first question)."

        # Format QA history for the prompt
        qa_history_str = self._format_qa_history(qa_history)

        prompt = CONTEXT_EXTRACTION_PROMPT.format(
            role_title=role_title,
            current_stage=current_stage,
            questions_remaining=questions_remaining,
            resume_summary=resume_summary,
            match_summary=match_summary or "Not available",
            qa_history=qa_history_str,
            latest_question=latest_question,
            latest_answer=latest_answer,
            latest_score=latest_score,
            latest_recommendation=latest_recommendation,
            latest_strengths="; ".join(latest_strengths) if latest_strengths else "None identified",
            latest_improvements="; ".join(latest_improvements) if latest_improvements else "None identified",
            existing_context=existing_context_str,
        )

        messages = [
            system_message(
                "You are a precise interview analysis engine. "
                "Output ONLY valid JSON, no markdown fences."
            ),
            user_message(prompt),
        ]

        try:
            response = await self.llm.generate(messages, self._config)
            extraction = self._parse_json_response(response.content)

            if extraction:
                self._merge_extraction(ctx, extraction)
                logger.info(
                    f"Context updated: {len(ctx.demonstrated_skills)} skills, "
                    f"{len(ctx.weak_areas)} weak areas, "
                    f"{len(ctx.follow_up_hooks)} hooks"
                )
            else:
                logger.warning("Context extraction returned empty result, keeping existing context")

        except Exception as e:
            logger.error(f"Context extraction LLM call failed: {e}")
            # Graceful degradation — return context with just the QA history updated

        return ctx

    def should_follow_up(
        self,
        context: CandidateContext,
        latest_score: float,
        latest_recommendation: str,
        follow_ups_so_far: int,
        max_follow_ups: int,
        questions_remaining: int,
        # --- new config-driven params ---
        answer_text: str = "",
        dont_know_follow_ups_so_far: int = 0,
        max_after_dont_know: int = 1,
        poor_score_threshold: float = 40,
        poor_recommendations: list | None = None,
        standout_score_threshold: float = 70,
        hooks_trigger_alone: bool = False,
    ) -> bool:
        """
        Decide whether a follow-up sub-question is warranted.

        This is a fast, rule-based check.  The actual follow-up question
        generation is done by QuestionGenerator.generate_followup_subquestion()
        which includes an LLM call with its own "should I actually ask this?"
        gate.

        Returns True if the orchestrator should attempt to generate a follow-up.
        """
        if poor_recommendations is None:
            poor_recommendations = ["weak", "insufficient", "concerning"]

        # Hard limits
        if follow_ups_so_far >= max_follow_ups:
            return False
        if questions_remaining < 3:
            # Preserve time for coverage
            return False

        # "I don't know" / gave-up limit
        if is_dont_know_answer(answer_text) and dont_know_follow_ups_so_far >= max_after_dont_know:
            return False

        # Trigger conditions
        has_hooks = len(context.follow_up_hooks) > 0
        poor_on_critical = (
            latest_score < poor_score_threshold
            and latest_recommendation in poor_recommendations
        )
        has_standout = (
            len(context.standout_points) > 0
            and latest_score >= standout_score_threshold
        )

        if hooks_trigger_alone:
            return has_hooks or poor_on_critical or has_standout
        else:
            # Hooks only amplify — they can't trigger alone
            if poor_on_critical or has_standout:
                return True
            # hooks present but only as amplifier → not enough on their own
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _format_qa_history(self, qa_history: List[Dict[str, Any]]) -> str:
        """Format QA history into a readable string for the prompt."""
        if not qa_history:
            return "No prior questions answered."

        lines: List[str] = []
        for i, qa in enumerate(qa_history, 1):
            lines.append(f"Q{i} [{qa.get('stage', '?')}] (score: {qa.get('score', '?')}/100):")
            lines.append(f"  Question: {qa.get('question', 'N/A')}")
            answer = qa.get("answer", "N/A")
            # Truncate very long answers to keep prompt manageable
            if len(answer) > 500:
                answer = answer[:500] + "..."
            lines.append(f"  Answer: {answer}")
            strengths = qa.get("strengths", [])
            if strengths:
                lines.append(f"  Strengths: {'; '.join(strengths[:3])}")
            improvements = qa.get("improvements", [])
            if improvements:
                lines.append(f"  Improvements: {'; '.join(improvements[:3])}")
            lines.append("")

        return "\n".join(lines)

    def _parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from LLM response, handling common formatting issues."""
        text = response.strip()

        # Strip markdown fences
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip()

        # Find JSON object bounds
        if not text.startswith("{"):
            start = text.find("{")
            if start != -1:
                text = text[start:]
        if not text.endswith("}"):
            end = text.rfind("}")
            if end != -1:
                text = text[: end + 1]

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse context extraction JSON: {e}")
            logger.debug(f"Response was: {text[:500]}")
            return None

    def _merge_extraction(self, ctx: CandidateContext, extraction: Dict[str, Any]) -> None:
        """Merge LLM extraction results into the running context, deduplicating."""
        # Replace lists entirely with latest LLM output (the prompt sees full
        # history, so the LLM's latest output is the authoritative cumulative view).
        ctx.demonstrated_skills = _dedup(extraction.get("demonstrated_skills", ctx.demonstrated_skills))
        ctx.weak_areas = _dedup(extraction.get("weak_areas", ctx.weak_areas))
        ctx.standout_points = _dedup(extraction.get("standout_points", ctx.standout_points))
        ctx.follow_up_hooks = _dedup(extraction.get("follow_up_hooks", ctx.follow_up_hooks))
        ctx.cross_stage_connections = _dedup(
            extraction.get("cross_stage_connections", ctx.cross_stage_connections)
        )
        ctx.confidence_assessment = extraction.get("confidence_assessment", ctx.confidence_assessment)
        ctx.suggested_focus = extraction.get("suggested_focus", ctx.suggested_focus)


def _dedup(items: List[str]) -> List[str]:
    """Deduplicate while preserving order."""
    seen: set = set()
    result: List[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item.strip())
    return result


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_builder: Optional[CandidateContextBuilder] = None


def get_candidate_context_builder() -> CandidateContextBuilder:
    """Get or create the singleton CandidateContextBuilder."""
    global _builder
    if _builder is None:
        _builder = CandidateContextBuilder()
    return _builder
