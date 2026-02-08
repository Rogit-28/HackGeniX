"""
Semantic matching service for JD-Resume matching.

Uses sentence-transformers with bge-large-en-v1.5 for embeddings
and cosine similarity for matching.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
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
        if model_name is None or device is None:
            config = load_model_config()
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
        
        # Weights for different matching components
        self.weights = {
            "semantic": 0.35,      # Overall semantic similarity
            "skills": 0.40,        # Skill match
            "experience": 0.25,    # Experience match
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
        for exp in resume.experience[:3]:  # Top 3 experiences
            if exp.description:
                resume_parts.append(exp.description)
            if exp.highlights:
                resume_parts.extend(exp.highlights[:3])
        
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
    
    async def match(
        self,
        resume: ParsedResume,
        job_description: ParsedJobDescription,
        resume_id: str,
        job_description_id: str,
    ) -> MatchResult:
        """
        Perform full matching between a resume and job description.
        
        Args:
            resume: Parsed resume data
            job_description: Parsed job description data
            resume_id: ID of the resume document
            job_description_id: ID of the job description document
            
        Returns:
            Complete match result with scores and recommendations
        """
        logger.info(f"Matching resume {resume_id} against JD {job_description_id}")
        
        # Compute individual scores
        semantic_score = self.compute_semantic_similarity(resume, job_description)
        skill_score, matched_skills, missing_skills = self.compute_skill_match(resume, job_description)
        experience_score = self.compute_experience_match(resume, job_description)
        
        # Compute weighted overall score
        overall_score = (
            semantic_score * self.weights["semantic"] +
            skill_score * self.weights["skills"] +
            experience_score * self.weights["experience"]
        )
        
        # Generate recommendations
        recommendations = self.generate_recommendations(
            resume, job_description, missing_skills, overall_score
        )
        
        logger.info(
            f"Match complete: overall={overall_score:.1f}, "
            f"semantic={semantic_score:.1f}, skills={skill_score:.1f}, "
            f"experience={experience_score:.1f}"
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
        )
    
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
