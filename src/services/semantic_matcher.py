"""
Semantic matching service for JD-Resume matching.

Uses sentence-transformers with bge-large-en-v1.5 for embeddings
and cosine similarity for matching.

Optionally runs an LLM qualitative sidecar (hybrid mode) controlled
by the ``matching`` section in ``config/models.yaml``.
"""
import asyncio
import json
import logging
from typing import AsyncIterator, List, Dict, Any, Optional, Tuple, Union
import numpy as np

import torch
from sentence_transformers import SentenceTransformer

from src.models.documents import ParsedResume, ParsedJobDescription, MatchResult
from src.core.config import load_model_config

logger = logging.getLogger(__name__)


def get_best_device() -> str:
    """Determine the best available device (cuda if available, else cpu)."""
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class SemanticMatcher:
    """
    Semantic matching service for comparing resumes against job descriptions.
    
    Uses embeddings for semantic similarity and skill matching.
    """
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
    ):
        """
        Initialize the semantic matcher.
        
        Args:
            model_name: Name of the sentence-transformers model
            device: Device to run the model on (cuda/cpu)
        """
        # Load config if not provided
        config = load_model_config()
        if model_name is None or device is None:
            embeddings_config = config.get("providers", {}).get("embeddings", {})
            model_name = model_name or embeddings_config.get("model", "BAAI/bge-large-en-v1.5")
            config_device = embeddings_config.get("device", "auto")
            # Auto-detect device if set to 'cuda' but CUDA not available
            if device is None:
                if config_device == "auto" or config_device == "cuda":
                    device = get_best_device()
                else:
                    device = config_device
        
        logger.info(f"Loading embedding model: {model_name} on {device}")
        self.model = SentenceTransformer(model_name, device=device)
        self.model_name = model_name
        self.device = device
        logger.info(f"Embedding model loaded: {model_name} on {device}")
        
        # LLM matching sidecar config
        matching_config = config.get("providers", {}).get("matching", {})
        self.llm_enabled: bool = matching_config.get("enabled", False)
        self.matching_provider: str = matching_config.get("provider", "ollama")
        self.matching_model: str = matching_config.get("model", "qwen2.5:3b")
        self.matching_max_tokens: int = matching_config.get("max_tokens", 1024)
        self.matching_temperature: float = matching_config.get("temperature", 0.1)
        
        # Weight presets
        self.weights_core = {
            "semantic": 0.35,
            "skills": 0.40,
            "experience": 0.25,
        }
        self.weights_hybrid = {
            "semantic": 0.25,
            "skills": 0.30,
            "experience": 0.20,
            "llm_fit": 0.25,
        }
    
    def encode(self, texts: List[str], normalize: bool = True) -> np.ndarray:
        """
        Encode texts to embeddings.
        
        Args:
            texts: List of texts to encode
            normalize: Whether to normalize embeddings (for cosine similarity)
            
        Returns:
            NumPy array of embeddings
        """
        embeddings = self.model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=normalize,
            show_progress_bar=False,
        )
        return embeddings
    
    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """
        Compute cosine similarity between two vectors.
        
        Args:
            a: First vector
            b: Second vector
            
        Returns:
            Cosine similarity score (0-1)
        """
        if a.ndim == 1:
            a = a.reshape(1, -1)
        if b.ndim == 1:
            b = b.reshape(1, -1)
        
        # If normalized, dot product equals cosine similarity
        similarity = np.dot(a, b.T)
        return float(similarity[0, 0])
    
    def compute_semantic_similarity(
        self,
        resume: ParsedResume,
        job_description: ParsedJobDescription,
    ) -> float:
        """
        Compute overall semantic similarity between resume and JD.
        
        Args:
            resume: Parsed resume data
            job_description: Parsed job description data
            
        Returns:
            Semantic similarity score (0-100)
        """
        # Build resume text representation
        resume_parts = []
        if resume.summary:
            resume_parts.append(resume.summary)
        if resume.skills:
            resume_parts.append("Skills: " + ", ".join(resume.skills))
        if resume.areas_of_interest:
            resume_parts.append("Areas of Interest: " + ", ".join(resume.areas_of_interest))
        if resume.soft_skills:
            resume_parts.append("Soft Skills: " + ", ".join(resume.soft_skills))
        for exp in resume.experience[:3]:  # Top 3 experiences
            if exp.description:
                resume_parts.append(exp.description)
            if exp.highlights:
                resume_parts.extend(exp.highlights[:3])
        for proj in resume.projects[:3]:  # Top 3 projects
            if proj.description:
                resume_parts.append(proj.description)
            if proj.highlights:
                resume_parts.extend(proj.highlights[:3])
            if proj.tech_stack:
                resume_parts.append("Technologies: " + ", ".join(proj.tech_stack))
        for res in resume.research[:2]:  # Top 2 research entries
            if res.highlights:
                resume_parts.extend(res.highlights[:2])
        
        resume_text = " ".join(resume_parts) if resume_parts else resume.raw_text[:2000]
        
        # Build JD text representation
        jd_parts = []
        if job_description.required_skills:
            jd_parts.append("Required Skills: " + ", ".join(job_description.required_skills))
        if job_description.responsibilities:
            jd_parts.extend(job_description.responsibilities[:5])
        if job_description.qualifications:
            jd_parts.extend(job_description.qualifications[:5])
        
        jd_text = " ".join(jd_parts) if jd_parts else job_description.raw_text[:2000]
        
        # Encode and compute similarity
        resume_emb = self.encode([resume_text])[0]
        jd_emb = self.encode([jd_text])[0]
        
        similarity = self.cosine_similarity(resume_emb, jd_emb)
        
        # Convert to 0-100 scale (similarity is already 0-1 for normalized vectors)
        return float(max(0, min(100, similarity * 100)))
    
    def compute_skill_match(
        self,
        resume: ParsedResume,
        job_description: ParsedJobDescription,
    ) -> Tuple[float, List[str], List[str]]:
        """
        Compute skill match between resume and JD.
        
        Uses both exact matching and semantic similarity for soft matches.
        
        Args:
            resume: Parsed resume data
            job_description: Parsed job description data
            
        Returns:
            Tuple of (score, matched_skills, missing_skills)
        """
        resume_skills = set(s.lower() for s in resume.skills)
        required_skills = set(s.lower() for s in job_description.required_skills)
        
        if not required_skills:
            return 100.0, list(resume_skills), []
        
        # Exact matches
        exact_matches = resume_skills & required_skills
        missing = required_skills - resume_skills
        
        # For non-exact matches, try semantic similarity
        soft_matches = []
        remaining_missing = []
        
        if missing and resume_skills:
            resume_skill_list = list(resume_skills - exact_matches)
            missing_skill_list = list(missing)
            
            if resume_skill_list and missing_skill_list:
                # Encode skills
                resume_embs = self.encode(resume_skill_list)
                missing_embs = self.encode(missing_skill_list)
                
                # Find soft matches (similarity > 0.7)
                for i, missing_skill in enumerate(missing_skill_list):
                    similarities = np.dot(resume_embs, missing_embs[i])
                    max_sim = float(np.max(similarities))
                    if max_sim > 0.7:
                        matched_idx = int(np.argmax(similarities))
                        soft_matches.append((missing_skill, resume_skill_list[matched_idx], max_sim))
                    else:
                        remaining_missing.append(missing_skill)
            else:
                remaining_missing = missing_skill_list
        else:
            remaining_missing = list(missing)
        
        # Calculate score
        total_required = len(required_skills)
        exact_score = len(exact_matches) / total_required
        soft_score = len(soft_matches) * 0.8 / total_required  # Soft matches count 80%
        
        final_score = min(1.0, exact_score + soft_score) * 100
        
        # Build matched skills list
        matched_skills = list(exact_matches) + [m[0] for m in soft_matches]
        
        return float(final_score), matched_skills, remaining_missing
    
    def compute_experience_match(
        self,
        resume: ParsedResume,
        job_description: ParsedJobDescription,
    ) -> float:
        """
        Compute experience match between resume and JD.
        
        Args:
            resume: Parsed resume data
            job_description: Parsed job description data
            
        Returns:
            Experience match score (0-100)
        """
        # Check experience years requirement
        if job_description.experience_years_min is not None:
            required_years = job_description.experience_years_min
            
            # Estimate candidate years from experience entries
            candidate_years = len(resume.experience) * 2  # Rough estimate: 2 years per role
            
            if candidate_years >= required_years:
                experience_score = 100
            elif candidate_years >= required_years * 0.7:
                experience_score = 70
            else:
                experience_score = max(0, (candidate_years / required_years) * 100)
        else:
            # No specific requirement, base on presence of experience
            if resume.experience:
                experience_score = 80
            else:
                experience_score = 40
        
        return float(experience_score)
    
    async def compute_llm_fit_assessment(
        self,
        resume: ParsedResume,
        job_description: ParsedJobDescription,
        semantic_score: float,
        skill_score: float,
        experience_score: float,
        matched_skills: List[str],
        missing_skills: List[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Run the LLM qualitative sidecar to assess candidate-JD fit.

        Returns a dict with fit_score, reasoning, transferable_skills,
        experience_quality, risk_flags, and strengths — or None on failure.
        """
        try:
            from src.providers.llm import LLMProviderFactory
            from src.providers.llm.base import GenerationConfig, user_message, system_message
            from src.services.prompts import LLM_MATCH_ASSESSMENT_PROMPT

            # Build the LLM provider for the matching config
            llm = LLMProviderFactory.create(
                provider_type=self.matching_provider,
                model=self.matching_model,
            )

            # ----- Format resume sections into readable strings -----
            experience_lines = []
            for exp in resume.experience:
                parts = []
                if exp.title:
                    parts.append(exp.title)
                if exp.company:
                    parts.append(f"@ {exp.company}")
                dates = ""
                if exp.start_date:
                    dates = exp.start_date
                if exp.end_date:
                    dates += f" - {exp.end_date}"
                if dates:
                    parts.append(f"({dates})")
                header = " ".join(parts)
                bullets = "; ".join(exp.highlights[:4]) if exp.highlights else (exp.description or "")
                experience_lines.append(f"- {header}: {bullets}" if bullets else f"- {header}")

            project_lines = []
            for proj in resume.projects:
                name = proj.name or "Unnamed project"
                desc = proj.description or ""
                tech = ", ".join(proj.tech_stack) if proj.tech_stack else ""
                line = f"- {name}: {desc}"
                if tech:
                    line += f" [{tech}]"
                project_lines.append(line)

            research_lines = []
            for res in resume.research:
                title = res.title or "Untitled"
                venue = f" ({res.venue})" if res.venue else ""
                highlights = "; ".join(res.highlights[:2]) if res.highlights else ""
                line = f"- {title}{venue}"
                if highlights:
                    line += f": {highlights}"
                research_lines.append(line)

            responsibilities_lines = [f"- {r}" for r in job_description.responsibilities[:8]]
            qualifications_lines = [f"- {q}" for q in job_description.qualifications[:8]]

            prompt = LLM_MATCH_ASSESSMENT_PROMPT.format(
                semantic_score=f"{semantic_score:.1f}",
                skill_score=f"{skill_score:.1f}",
                experience_score=f"{experience_score:.1f}",
                matched_skills=", ".join(matched_skills) if matched_skills else "none",
                missing_skills=", ".join(missing_skills) if missing_skills else "none",
                resume_skills=", ".join(resume.skills) if resume.skills else "none listed",
                resume_experience="\n".join(experience_lines) if experience_lines else "No experience listed",
                resume_projects="\n".join(project_lines) if project_lines else "No projects listed",
                resume_research="\n".join(research_lines) if research_lines else "No research listed",
                resume_interests=", ".join(resume.areas_of_interest) if resume.areas_of_interest else "none listed",
                jd_title=job_description.title or "Unknown",
                jd_required_skills=", ".join(job_description.required_skills) if job_description.required_skills else "none listed",
                jd_preferred_skills=", ".join(job_description.preferred_skills) if job_description.preferred_skills else "none listed",
                jd_responsibilities="\n".join(responsibilities_lines) if responsibilities_lines else "Not specified",
                jd_qualifications="\n".join(qualifications_lines) if qualifications_lines else "Not specified",
            )

            messages = [
                system_message(
                    "You are a hiring assessment engine. Return ONLY valid JSON. "
                    "No markdown fences, no commentary."
                ),
                user_message(prompt),
            ]

            logger.info("Running LLM fit assessment...")
            response = await llm.generate(
                messages,
                GenerationConfig(
                    max_tokens=self.matching_max_tokens,
                    temperature=self.matching_temperature,
                    json_mode=True,
                ),
            )

            # Parse JSON from response
            raw = response.content.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            data = json.loads(raw)

            # Validate and clamp fit_score
            fit_score = data.get("fit_score")
            if fit_score is None:
                logger.warning("LLM response missing fit_score, discarding result")
                return None
            fit_score = max(0, min(100, int(fit_score)))

            result = {
                "fit_score": float(fit_score),
                "reasoning": data.get("reasoning", ""),
                "transferable_skills": data.get("transferable_skills", []),
                "experience_quality": data.get("experience_quality"),
                "experience_quality_reasoning": data.get("experience_quality_reasoning"),
                "risk_flags": data.get("risk_flags", []),
                "strengths": data.get("strengths", []),
            }

            logger.info(f"LLM fit assessment complete: fit_score={fit_score}")
            return result

        except json.JSONDecodeError as e:
            logger.warning(f"LLM returned invalid JSON for fit assessment: {e}")
            return None
        except Exception as e:
            logger.warning(f"LLM fit assessment failed (falling back to core-only): {e}")
            return None

    def generate_recommendations(
        self,
        resume: ParsedResume,
        job_description: ParsedJobDescription,
        missing_skills: List[str],
        overall_score: float,
    ) -> List[str]:
        """
        Generate recommendations for the candidate.
        
        Args:
            resume: Parsed resume data
            job_description: Parsed job description data
            missing_skills: List of skills the candidate is missing
            overall_score: Overall match score
            
        Returns:
            List of recommendations
        """
        recommendations = []
        
        if missing_skills:
            top_missing = missing_skills[:5]
            recommendations.append(
                f"Consider learning these required skills: {', '.join(top_missing)}"
            )
        
        if overall_score < 50:
            recommendations.append(
                "The candidate may not be a strong fit for this role based on current qualifications."
            )
        elif overall_score < 70:
            recommendations.append(
                "The candidate shows potential but may need additional training or experience."
            )
        else:
            recommendations.append(
                "The candidate appears to be a good match for this role."
            )
        
        # Experience-based recommendations
        if job_description.experience_years_min:
            if len(resume.experience) < job_description.experience_years_min // 2:
                recommendations.append(
                    f"The role requires {job_description.experience_years_min}+ years of experience. "
                    "Consider candidates with more senior backgrounds."
                )
        
        return recommendations
    
    def _compute_core_scores(
        self,
        resume: ParsedResume,
        job_description: ParsedJobDescription,
    ) -> Tuple[float, float, List[str], List[str], float]:
        """
        Compute all CPU/GPU-bound scores in a single synchronous call.
        
        Designed to be called via asyncio.to_thread() so the embedding
        inference does not block the event loop.
        
        Returns:
            (semantic_score, skill_score, matched_skills, missing_skills, experience_score)
        """
        semantic_score = self.compute_semantic_similarity(resume, job_description)
        skill_score, matched_skills, missing_skills = self.compute_skill_match(resume, job_description)
        experience_score = self.compute_experience_match(resume, job_description)
        return semantic_score, skill_score, matched_skills, missing_skills, experience_score
    
    async def match(
        self,
        resume: ParsedResume,
        job_description: ParsedJobDescription,
        resume_id: str,
        job_description_id: str,
        use_llm: bool = True,
    ) -> MatchResult:
        """
        Perform full matching between a resume and job description.
        
        Args:
            resume: Parsed resume data
            job_description: Parsed job description data
            resume_id: ID of the resume document
            job_description_id: ID of the job description document
            use_llm: Whether to run the LLM sidecar (requires config enabled too)
            
        Returns:
            Complete match result with scores and recommendations
        """
        logger.info(f"Matching resume {resume_id} against JD {job_description_id}")
        
        # Offload CPU/GPU-bound embedding inference to a thread so we
        # don't block the async event loop.
        (semantic_score, skill_score, matched_skills,
         missing_skills, experience_score) = await asyncio.to_thread(
            self._compute_core_scores, resume, job_description
        )
        
        # ----- LLM sidecar (optional) -----
        llm_result: Optional[Dict[str, Any]] = None
        run_llm = use_llm and self.llm_enabled

        if run_llm:
            llm_result = await self.compute_llm_fit_assessment(
                resume=resume,
                job_description=job_description,
                semantic_score=semantic_score,
                skill_score=skill_score,
                experience_score=experience_score,
                matched_skills=matched_skills,
                missing_skills=missing_skills,
            )

        # ----- Weighted overall score -----
        if llm_result is not None:
            weights = self.weights_hybrid
            overall_score = (
                semantic_score * weights["semantic"]
                + skill_score * weights["skills"]
                + experience_score * weights["experience"]
                + llm_result["fit_score"] * weights["llm_fit"]
            )
        else:
            weights = self.weights_core
            overall_score = (
                semantic_score * weights["semantic"]
                + skill_score * weights["skills"]
                + experience_score * weights["experience"]
            )
        
        # Generate recommendations
        recommendations = self.generate_recommendations(
            resume, job_description, missing_skills, overall_score
        )
        
        logger.info(
            f"Match complete: overall={overall_score:.1f}, "
            f"semantic={semantic_score:.1f}, skills={skill_score:.1f}, "
            f"experience={experience_score:.1f}, "
            f"llm={'on (score=' + str(llm_result['fit_score']) + ')' if llm_result else 'off'}"
        )
        
        return MatchResult(
            resume_id=resume_id,
            job_description_id=job_description_id,
            overall_score=overall_score,
            skill_match_score=skill_score,
            experience_match_score=experience_score,
            semantic_similarity_score=semantic_score,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            recommendations=recommendations,
            # LLM sidecar fields
            llm_fit_score=llm_result["fit_score"] if llm_result else None,
            llm_reasoning=llm_result["reasoning"] if llm_result else None,
            transferable_skills=llm_result.get("transferable_skills", []) if llm_result else [],
            experience_quality=llm_result.get("experience_quality") if llm_result else None,
            experience_quality_reasoning=llm_result.get("experience_quality_reasoning") if llm_result else None,
            risk_flags=llm_result.get("risk_flags", []) if llm_result else [],
            strengths=llm_result.get("strengths", []) if llm_result else [],
            llm_enabled=llm_result is not None,
        )

    async def match_stream(
        self,
        resume: ParsedResume,
        job_description: ParsedJobDescription,
        resume_id: str,
        job_description_id: str,
        use_llm: bool = True,
    ) -> AsyncIterator[Union["StreamEvent", MatchResult]]:
        """
        Perform matching with SSE progress streaming.

        Yields StreamEvent objects for each stage of the matching pipeline,
        and a final MatchResult as the last item.
        """
        from src.services.streaming import (
            StreamEvent, EventType, status_event, progress_event,
            result_event, error_event, done_event,
            stream_llm_generation,
        )

        logger.info(f"Streaming match: resume {resume_id} against JD {job_description_id}")

        # --- Stage 1: Embedding & algorithmic scores ---
        yield status_event("embeddings", "Computing semantic embeddings...")

        (semantic_score, skill_score, matched_skills,
         missing_skills, experience_score) = await asyncio.to_thread(
            self._compute_core_scores, resume, job_description
        )

        yield progress_event(
            "embeddings",
            f"Semantic: {semantic_score:.1f}, Skills: {skill_score:.1f}, Experience: {experience_score:.1f}",
            semantic_score=round(semantic_score, 1),
            skill_score=round(skill_score, 1),
            experience_score=round(experience_score, 1),
            matched_skills=matched_skills,
            missing_skills=missing_skills,
        )

        # --- Stage 2: LLM fit assessment (optional, now with token streaming) ---
        llm_result: Optional[Dict[str, Any]] = None
        run_llm = use_llm and self.llm_enabled

        if run_llm:
            yield status_event("llm_assessment", "Running AI fit assessment...")

            try:
                from src.providers.llm import LLMProviderFactory
                from src.providers.llm.base import GenerationConfig, user_message as um, system_message as sm
                from src.services.prompts import LLM_MATCH_ASSESSMENT_PROMPT

                llm = LLMProviderFactory.create(
                    provider_type=self.matching_provider,
                    model=self.matching_model,
                )

                # ----- Format resume sections -----
                experience_lines = []
                for exp in resume.experience:
                    parts = []
                    if exp.title:
                        parts.append(exp.title)
                    if exp.company:
                        parts.append(f"@ {exp.company}")
                    dates = ""
                    if exp.start_date:
                        dates = exp.start_date
                    if exp.end_date:
                        dates += f" - {exp.end_date}"
                    if dates:
                        parts.append(f"({dates})")
                    header = " ".join(parts)
                    bullets = "; ".join(exp.highlights[:4]) if exp.highlights else (exp.description or "")
                    experience_lines.append(f"- {header}: {bullets}" if bullets else f"- {header}")

                project_lines = []
                for proj in resume.projects:
                    name = proj.name or "Unnamed project"
                    desc = proj.description or ""
                    tech = ", ".join(proj.tech_stack) if proj.tech_stack else ""
                    line = f"- {name}: {desc}"
                    if tech:
                        line += f" [{tech}]"
                    project_lines.append(line)

                research_lines = []
                for res in resume.research:
                    title = res.title or "Untitled"
                    venue = f" ({res.venue})" if res.venue else ""
                    highlights = "; ".join(res.highlights[:2]) if res.highlights else ""
                    line = f"- {title}{venue}"
                    if highlights:
                        line += f": {highlights}"
                    research_lines.append(line)

                responsibilities_lines = [f"- {r}" for r in job_description.responsibilities[:8]]
                qualifications_lines = [f"- {q}" for q in job_description.qualifications[:8]]

                prompt = LLM_MATCH_ASSESSMENT_PROMPT.format(
                    semantic_score=f"{semantic_score:.1f}",
                    skill_score=f"{skill_score:.1f}",
                    experience_score=f"{experience_score:.1f}",
                    matched_skills=", ".join(matched_skills) if matched_skills else "none",
                    missing_skills=", ".join(missing_skills) if missing_skills else "none",
                    resume_skills=", ".join(resume.skills) if resume.skills else "none listed",
                    resume_experience="\n".join(experience_lines) if experience_lines else "No experience listed",
                    resume_projects="\n".join(project_lines) if project_lines else "No projects listed",
                    resume_research="\n".join(research_lines) if research_lines else "No research listed",
                    resume_interests=", ".join(resume.areas_of_interest) if resume.areas_of_interest else "none listed",
                    jd_title=job_description.title or "Unknown",
                    jd_required_skills=", ".join(job_description.required_skills) if job_description.required_skills else "none listed",
                    jd_preferred_skills=", ".join(job_description.preferred_skills) if job_description.preferred_skills else "none listed",
                    jd_responsibilities="\n".join(responsibilities_lines) if responsibilities_lines else "Not specified",
                    jd_qualifications="\n".join(qualifications_lines) if qualifications_lines else "Not specified",
                )

                messages = [
                    sm(
                        "You are a hiring assessment engine. Return ONLY valid JSON. "
                        "No markdown fences, no commentary."
                    ),
                    um(prompt),
                ]

                llm_config = GenerationConfig(
                    max_tokens=self.matching_max_tokens,
                    temperature=self.matching_temperature,
                    json_mode=False,
                )

                # Stream tokens, accumulate, parse JSON
                accumulated: list[str] = []
                async for event in stream_llm_generation(llm, messages, llm_config, stage="llm_assessment"):
                    if event.type == EventType.TOKEN:
                        accumulated.append(event.data["content"])
                    yield event  # forward all events (token, progress, status)

                full_response = "".join(accumulated)

                # Parse JSON from accumulated response
                raw = full_response.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                    if raw.endswith("```"):
                        raw = raw[:-3]
                    raw = raw.strip()

                data = json.loads(raw)

                fit_score = data.get("fit_score")
                if fit_score is not None:
                    fit_score = max(0, min(100, int(fit_score)))
                    llm_result = {
                        "fit_score": float(fit_score),
                        "reasoning": data.get("reasoning", ""),
                        "transferable_skills": data.get("transferable_skills", []),
                        "experience_quality": data.get("experience_quality"),
                        "experience_quality_reasoning": data.get("experience_quality_reasoning"),
                        "risk_flags": data.get("risk_flags", []),
                        "strengths": data.get("strengths", []),
                    }
                    yield progress_event(
                        "llm_assessment",
                        f"AI fit score: {fit_score}",
                        fit_score=float(fit_score),
                    )
                else:
                    logger.warning("LLM response missing fit_score")
                    yield progress_event(
                        "llm_assessment",
                        "AI assessment returned no fit score, using algorithmic scores only",
                    )

            except json.JSONDecodeError as e:
                logger.warning(f"LLM returned invalid JSON for fit assessment: {e}")
                yield progress_event(
                    "llm_assessment",
                    "AI assessment unavailable, using algorithmic scores only",
                )
            except Exception as e:
                logger.warning(f"LLM fit assessment failed: {e}")
                yield progress_event(
                    "llm_assessment",
                    "AI assessment unavailable, using algorithmic scores only",
                )

        # --- Stage 3: Compute final score ---
        yield status_event("scoring", "Computing final score...")

        if llm_result is not None:
            weights = self.weights_hybrid
            overall_score = (
                semantic_score * weights["semantic"]
                + skill_score * weights["skills"]
                + experience_score * weights["experience"]
                + llm_result["fit_score"] * weights["llm_fit"]
            )
        else:
            weights = self.weights_core
            overall_score = (
                semantic_score * weights["semantic"]
                + skill_score * weights["skills"]
                + experience_score * weights["experience"]
            )

        recommendations = self.generate_recommendations(
            resume, job_description, missing_skills, overall_score
        )

        logger.info(
            f"Stream match complete: overall={overall_score:.1f}, "
            f"semantic={semantic_score:.1f}, skills={skill_score:.1f}, "
            f"experience={experience_score:.1f}, "
            f"llm={'on (score=' + str(llm_result['fit_score']) + ')' if llm_result else 'off'}"
        )

        match_result = MatchResult(
            resume_id=resume_id,
            job_description_id=job_description_id,
            overall_score=overall_score,
            skill_match_score=skill_score,
            experience_match_score=experience_score,
            semantic_similarity_score=semantic_score,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            recommendations=recommendations,
            llm_fit_score=llm_result["fit_score"] if llm_result else None,
            llm_reasoning=llm_result["reasoning"] if llm_result else None,
            transferable_skills=llm_result.get("transferable_skills", []) if llm_result else [],
            experience_quality=llm_result.get("experience_quality") if llm_result else None,
            experience_quality_reasoning=llm_result.get("experience_quality_reasoning") if llm_result else None,
            risk_flags=llm_result.get("risk_flags", []) if llm_result else [],
            strengths=llm_result.get("strengths", []) if llm_result else [],
            llm_enabled=llm_result is not None,
        )

        # Yield the final result object (API layer wraps into result_event)
        yield match_result
    
    async def compute_embedding(self, text: str) -> List[float]:
        """
        Compute embedding for a single text.
        
        Useful for storing embeddings in the database for later retrieval.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding as a list of floats
        """
        embedding = self.encode([text])[0]
        return embedding.tolist()
    
    async def find_similar_resumes(
        self,
        job_description_embedding: List[float],
        resume_embeddings: List[Tuple[str, List[float]]],
        top_k: int = 10,
    ) -> List[Tuple[str, float]]:
        """
        Find top-k most similar resumes to a job description.
        
        Args:
            job_description_embedding: JD embedding vector
            resume_embeddings: List of (resume_id, embedding) tuples
            top_k: Number of results to return
            
        Returns:
            List of (resume_id, similarity_score) tuples, sorted by score
        """
        jd_emb = np.array(job_description_embedding)
        
        results = []
        for resume_id, resume_emb in resume_embeddings:
            similarity = self.cosine_similarity(jd_emb, np.array(resume_emb))
            results.append((resume_id, similarity))
        
        # Sort by similarity descending
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]


# Global matcher instance (lazy loaded)
_matcher: Optional[SemanticMatcher] = None


def get_semantic_matcher() -> SemanticMatcher:
    """Get or create the semantic matcher instance."""
    global _matcher
    if _matcher is None:
        _matcher = SemanticMatcher()
    return _matcher
