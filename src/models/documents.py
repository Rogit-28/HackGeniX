"""
Pydantic models for documents (resumes, job descriptions).
"""
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    """Type of document."""
    RESUME = "resume"
    JOB_DESCRIPTION = "job_description"


class ParsedEntity(BaseModel):
    """Extracted named entity."""
    text: str
    label: str
    start: int
    end: int


class ContactInfo(BaseModel):
    """Parsed contact information from resume."""
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    location: Optional[str] = None


class Education(BaseModel):
    """Education entry."""
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[float] = None


class Experience(BaseModel):
    """Work experience entry."""
    company: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)


class ParsedResume(BaseModel):
    """Fully parsed resume data."""
    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    experience: List[Experience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    entities: List[ParsedEntity] = Field(default_factory=list)
    raw_text: str = ""


class ParsedJobDescription(BaseModel):
    """Fully parsed job description data."""
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None  # full-time, part-time, contract
    experience_level: Optional[str] = None  # junior, mid, senior
    experience_years_min: Optional[int] = None
    experience_years_max: Optional[int] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)
    qualifications: List[str] = Field(default_factory=list)
    benefits: List[str] = Field(default_factory=list)
    raw_text: str = ""


class ResumeDocument(BaseModel):
    """Resume document stored in database."""
    id: Optional[str] = Field(None, alias="_id")
    candidate_id: Optional[str] = None
    filename: str
    storage_key: str
    content_type: str
    file_size: int
    parsed_data: Optional[ParsedResume] = None
    embedding: Optional[List[float]] = None
    status: str = "pending"  # pending, processing, parsed, failed
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True


class JobDescriptionDocument(BaseModel):
    """Job description document stored in database."""
    id: Optional[str] = Field(None, alias="_id")
    title: str
    company: Optional[str] = None
    filename: Optional[str] = None
    storage_key: Optional[str] = None
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    parsed_data: Optional[ParsedJobDescription] = None
    embedding: Optional[List[float]] = None
    status: str = "pending"
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True


# API Request/Response Models

class ResumeUploadResponse(BaseModel):
    """Response after uploading a resume."""
    id: str
    filename: str
    status: str
    message: str
    parsed_data: Optional[ParsedResume] = None


class JobDescriptionCreateRequest(BaseModel):
    """Request to create a job description."""
    title: str
    company: Optional[str] = None
    description: str


class JobDescriptionUploadResponse(BaseModel):
    """Response after uploading a job description file."""
    id: str
    title: str
    company: Optional[str] = None
    filename: str
    status: str
    message: str
    parsed_data: Optional[ParsedJobDescription] = None


class JobDescriptionResponse(BaseModel):
    """Response with job description data."""
    id: str
    title: str
    company: Optional[str] = None
    status: str
    parsed_data: Optional[ParsedJobDescription] = None


class MatchResult(BaseModel):
    """Result of matching a resume against a job description."""
    resume_id: str
    job_description_id: str
    overall_score: float = Field(ge=0, le=100)
    skill_match_score: float = Field(ge=0, le=100)
    experience_match_score: float = Field(ge=0, le=100)
    semantic_similarity_score: float = Field(ge=0, le=100)
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
