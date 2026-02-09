"""
Document management API endpoints.

Handles resume and job description uploads, parsing, and matching.
"""
import logging
from typing import List, Optional
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Form

from src.core.database import get_db, mongodb_client
from src.core.storage import get_storage, StorageClient
from src.core.auth import get_current_user, require_role, require_permission
from src.core.permissions import Permissions
from src.models.auth import AuthenticatedUser, UserRole
from src.models.documents import (
    ResumeUploadResponse,
    JobDescriptionCreateRequest,
    JobDescriptionResponse,
    JobDescriptionUploadResponse,
    MatchResult,
    ResumeDocument,
    JobDescriptionDocument,
    ParsedResume,
    ParsedJobDescription,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# Allowed file types for resume upload
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/resumes", response_model=ResumeUploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    storage: StorageClient = Depends(get_storage),
    user: AuthenticatedUser = Depends(require_permission(Permissions.UPLOAD_DOCUMENT)),
):
    """
    Upload a resume file for parsing and analysis.
    
    The resume is parsed synchronously using LLM for robust extraction.
    
    Supported formats: PDF, DOC, DOCX
    Max file size: 10 MB
    """
    from src.services.document_processor import DocumentProcessor
    
    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: PDF, DOC, DOCX"
        )
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: 10 MB"
        )
    
    # Upload to storage
    storage_key = await storage.upload_bytes(
        data=content,
        filename=file.filename,
        category="resumes",
        content_type=file.content_type,
    )
    
    # Extract text and parse with LLM (mirrors the JD upload flow)
    processor = DocumentProcessor()
    
    try:
        raw_text = await processor.extract_text(content, file.content_type)
        parsed_data = await processor.parse_resume_with_llm(raw_text)
        status = "parsed"
        error_message = None
        logger.info(f"Resume parsed successfully: {file.filename}")
    except Exception as e:
        logger.error(f"Failed to parse resume {file.filename}: {e}")
        parsed_data = None
        status = "failed"
        error_message = str(e)
    
    # Create document record with parsed data
    doc = ResumeDocument(
        filename=file.filename,
        storage_key=storage_key,
        content_type=file.content_type,
        file_size=file_size,
        status=status,
        parsed_data=parsed_data,
        error_message=error_message,
    )
    
    # Insert into database
    result = await mongodb_client.resumes.insert_one(
        doc.model_dump(by_alias=True, exclude={"id"})
    )
    doc_id = str(result.inserted_id)
    
    logger.info(f"Resume uploaded: {file.filename} -> {doc_id} (status: {status})")
    
    return ResumeUploadResponse(
        id=doc_id,
        filename=file.filename,
        status=status,
        message=f"Resume uploaded and {'parsed successfully' if status == 'parsed' else 'parsing failed: ' + (error_message or 'unknown error')}",
        parsed_data=parsed_data,
    )


@router.get("/resumes/{resume_id}")
async def get_resume(
    resume_id: str,
    user: AuthenticatedUser = Depends(require_permission(Permissions.VIEW_DOCUMENT)),
):
    """
    Get resume details by ID.
    """
    try:
        doc = await mongodb_client.resumes.find_one({"_id": ObjectId(resume_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resume ID")
    
    if not doc:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("/resumes")
async def list_resumes(
    skip: int = 0,
    limit: int = 20,
    user: AuthenticatedUser = Depends(require_permission(Permissions.VIEW_DOCUMENT)),
):
    """
    List all resumes with pagination.
    """
    cursor = mongodb_client.resumes.find().skip(skip).limit(limit).sort("created_at", -1)
    resumes = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        resumes.append(doc)
    return {"resumes": resumes, "skip": skip, "limit": limit}


@router.delete("/resumes/{resume_id}")
async def delete_resume(
    resume_id: str,
    storage: StorageClient = Depends(get_storage),
    user: AuthenticatedUser = Depends(require_permission(Permissions.DELETE_DOCUMENT)),
):
    """
    Delete a resume by ID.
    """
    try:
        doc = await mongodb_client.resumes.find_one({"_id": ObjectId(resume_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resume ID")
    
    if not doc:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Delete from storage
    await storage.delete_file(doc["storage_key"])
    
    # Delete from database
    await mongodb_client.resumes.delete_one({"_id": ObjectId(resume_id)})
    
    return {"message": "Resume deleted successfully"}


# Job Description Endpoints

@router.post("/job-descriptions", response_model=JobDescriptionResponse)
async def create_job_description(
    request: JobDescriptionCreateRequest,
    user: AuthenticatedUser = Depends(require_permission(Permissions.UPLOAD_DOCUMENT)),
):
    """
    Create a new job description from text for matching.
    
    The job description is parsed synchronously using LLM.
    """
    from src.services.document_processor import DocumentProcessor
    
    # Parse job description with LLM
    processor = DocumentProcessor()
    
    try:
        parsed_data = await processor.parse_job_description_with_llm(request.description)
        
        # Use provided title/company or fall back to extracted values
        final_title = request.title if request.title else (parsed_data.title or "Untitled Position")
        final_company = request.company if request.company else parsed_data.company
        
        # Update parsed_data with final values
        parsed_data.title = final_title
        parsed_data.company = final_company
        
        status = "parsed"
        error_message = None
        logger.info(f"JD parsed successfully: {final_title}")
    except Exception as e:
        logger.error(f"Failed to parse JD: {e}")
        final_title = request.title or "Untitled Position"
        final_company = request.company
        parsed_data = None
        status = "failed"
        error_message = str(e)
    
    doc = JobDescriptionDocument(
        title=final_title,
        company=final_company,
        parsed_data=parsed_data,
        status=status,
        error_message=error_message,
    )
    
    # Store raw text for reference
    doc_dict = doc.model_dump(by_alias=True, exclude={"id"})
    doc_dict["raw_text"] = request.description
    
    result = await mongodb_client.job_descriptions.insert_one(doc_dict)
    doc_id = str(result.inserted_id)
    
    logger.info(f"Job description created: {final_title} -> {doc_id} (status: {status})")
    
    return JobDescriptionResponse(
        id=doc_id,
        title=final_title,
        company=final_company,
        status=status,
        parsed_data=parsed_data,
    )


@router.post("/job-descriptions/upload", response_model=JobDescriptionUploadResponse)
async def upload_job_description(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    company: Optional[str] = Form(None),
    storage: StorageClient = Depends(get_storage),
    user: AuthenticatedUser = Depends(require_permission(Permissions.UPLOAD_DOCUMENT)),
):
    """
    Upload a job description file (PDF/DOCX) for parsing and analysis.
    
    If title and company are not provided, they will be extracted from the document using LLM.
    
    Supported formats: PDF, DOC, DOCX
    Max file size: 10 MB
    """
    from src.services.document_processor import DocumentProcessor
    
    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: PDF, DOC, DOCX"
        )
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: 10 MB"
        )
    
    # Upload to storage
    storage_key = await storage.upload_bytes(
        data=content,
        filename=file.filename,
        category="job_descriptions",
        content_type=file.content_type,
    )
    
    # Extract text and parse with LLM
    processor = DocumentProcessor()
    
    try:
        # Extract raw text from PDF/DOCX
        raw_text = await processor.extract_text(content, file.content_type)
        
        # Parse with LLM to extract structured data
        parsed_data = await processor.parse_job_description_with_llm(raw_text)
        
        # Use provided title/company or fall back to extracted values
        final_title = title if title and title.strip() else (parsed_data.title or file.filename)
        final_company = company if company and company.strip() else parsed_data.company
        
        # Update parsed_data with final values
        parsed_data.title = final_title
        parsed_data.company = final_company
        
        status = "parsed"
        error_message = None
        
    except Exception as e:
        logger.error(f"Failed to parse JD file {file.filename}: {e}")
        # Fall back to basic info
        final_title = title if title and title.strip() else file.filename
        final_company = company if company and company.strip() else None
        parsed_data = None
        status = "failed"
        error_message = str(e)
    
    # Create document record
    doc = JobDescriptionDocument(
        title=final_title,
        company=final_company,
        filename=file.filename,
        storage_key=storage_key,
        content_type=file.content_type,
        file_size=file_size,
        parsed_data=parsed_data,
        status=status,
        error_message=error_message,
    )
    
    # Insert into database
    doc_dict = doc.model_dump(by_alias=True, exclude={"id"})
    if parsed_data:
        doc_dict["raw_text"] = parsed_data.raw_text
    
    result = await mongodb_client.job_descriptions.insert_one(doc_dict)
    doc_id = str(result.inserted_id)
    
    logger.info(f"Job description uploaded: {file.filename} -> {doc_id} (status: {status})")
    
    return JobDescriptionUploadResponse(
        id=doc_id,
        title=final_title,
        company=final_company,
        filename=file.filename,
        status=status,
        message=f"Job description uploaded and {'parsed successfully' if status == 'parsed' else 'parsing failed: ' + (error_message or 'unknown error')}",
        parsed_data=parsed_data,
    )


@router.get("/job-descriptions/{jd_id}")
async def get_job_description(
    jd_id: str,
    user: AuthenticatedUser = Depends(require_permission(Permissions.VIEW_DOCUMENT)),
):
    """
    Get job description details by ID.
    """
    try:
        doc = await mongodb_client.job_descriptions.find_one({"_id": ObjectId(jd_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job description ID")
    
    if not doc:
        raise HTTPException(status_code=404, detail="Job description not found")
    
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("/job-descriptions")
async def list_job_descriptions(
    skip: int = 0,
    limit: int = 20,
    user: AuthenticatedUser = Depends(require_permission(Permissions.VIEW_DOCUMENT)),
):
    """
    List all job descriptions with pagination.
    """
    cursor = mongodb_client.job_descriptions.find().skip(skip).limit(limit).sort("created_at", -1)
    jds = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        jds.append(doc)
    return {"job_descriptions": jds, "skip": skip, "limit": limit}


# Matching Endpoints

@router.post("/match", response_model=MatchResult)
async def match_resume_to_job(
    resume_id: str,
    job_description_id: str,
    use_llm: bool = True,
    user: AuthenticatedUser = Depends(require_permission(Permissions.RUN_ANALYSIS)),
):
    """
    Match a resume against a job description.
    
    Returns match scores and analysis.
    
    Args:
        resume_id: ID of the uploaded resume
        job_description_id: ID of the job description
        use_llm: Enable LLM qualitative sidecar (default True).
                 Set to False for pure algorithmic matching.
    """
    # Validate resume exists
    try:
        resume = await mongodb_client.resumes.find_one({"_id": ObjectId(resume_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resume ID")
    
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Validate job description exists
    try:
        jd = await mongodb_client.job_descriptions.find_one({"_id": ObjectId(job_description_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job description ID")
    
    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")
    
    # Check if both documents are parsed
    if resume.get("status") != "parsed" or jd.get("status") != "parsed":
        raise HTTPException(
            status_code=400,
            detail="Both resume and job description must be parsed before matching"
        )
    
    # Reconstruct Pydantic models from stored dicts
    resume_parsed = resume.get("parsed_data")
    jd_parsed = jd.get("parsed_data")
    
    if not resume_parsed or not jd_parsed:
        raise HTTPException(
            status_code=400,
            detail="Parsed data missing from one or both documents. Please re-upload."
        )
    
    parsed_resume = ParsedResume(**resume_parsed)
    parsed_jd = ParsedJobDescription(**jd_parsed)
    
    # Run semantic matching
    from src.services.semantic_matcher import get_semantic_matcher
    
    matcher = get_semantic_matcher()
    result = await matcher.match(
        resume=parsed_resume,
        job_description=parsed_jd,
        resume_id=resume_id,
        job_description_id=job_description_id,
        use_llm=use_llm,
    )
    
    return result
