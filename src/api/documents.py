"""
Document management API endpoints.

Handles resume and job description uploads, parsing, and matching.
All parsing endpoints use Server-Sent Events (SSE) to stream progress
and results back to the client in real-time.
"""
import json
import logging
from typing import List, Optional, AsyncIterator
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Form, Query
from sse_starlette.sse import EventSourceResponse

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
from src.services.streaming import (
    StreamEvent, status_event, progress_event,
    result_event, error_event, done_event,
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


# ---------------------------------------------------------------------------
# Resume endpoints
# ---------------------------------------------------------------------------

@router.post("/resumes")
async def upload_resume(
    file: UploadFile = File(...),
    storage: StorageClient = Depends(get_storage),
    user: AuthenticatedUser = Depends(require_permission(Permissions.UPLOAD_DOCUMENT)),
):
    """
    Upload a resume file for parsing and analysis.

    Returns an SSE stream with progress events and the final parsed result.

    Supported formats: PDF, DOC, DOCX
    Max file size: 10 MB

    SSE event types:
        - status: pipeline stage transitions
        - progress: token generation progress
        - result: completed parsed data
        - error: processing errors
        - done: stream complete
    """
    from src.services.document_processor import DocumentProcessor

    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Allowed types: PDF, DOC, DOCX"
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File too large. Maximum size: 10 MB"
        )

    async def _stream_resume_upload() -> AsyncIterator[dict]:
        processor = DocumentProcessor()

        # Upload to storage
        yield status_event("uploading", "Uploading file to storage...").to_sse()
        try:
            storage_key = await storage.upload_bytes(
                data=content,
                filename=file.filename,
                category="resumes",
                content_type=file.content_type,
            )
        except Exception as e:
            yield error_event("uploading", f"Storage upload failed: {e}").to_sse()
            return

        # Extract text
        yield status_event("extracting", "Extracting text from document...").to_sse()
        try:
            raw_text = await processor.extract_text(content, file.content_type)
            yield progress_event(
                "extracting",
                f"Extracted {len(raw_text)} characters",
                chars=len(raw_text),
            ).to_sse()
        except Exception as e:
            yield error_event("extracting", f"Text extraction failed: {e}").to_sse()
            # Still create the DB record in failed state
            doc = ResumeDocument(
                filename=file.filename,
                storage_key=storage_key,
                content_type=file.content_type,
                file_size=file_size,
                status="failed",
                error_message=str(e),
            )
            result = await mongodb_client.resumes.insert_one(
                doc.model_dump(by_alias=True, exclude={"id"})
            )
            yield result_event("upload_record", {
                "id": str(result.inserted_id),
                "filename": file.filename,
                "status": "failed",
            }).to_sse()
            return

        # Stream LLM parsing
        parsed_data = None
        async for item in processor.parse_resume_with_llm_stream(raw_text):
            if isinstance(item, StreamEvent):
                yield item.to_sse()
            elif isinstance(item, ParsedResume):
                parsed_data = item

        # Determine final status
        doc_status = "parsed" if parsed_data and parsed_data.contact else "failed"
        error_message = None if doc_status == "parsed" else "Parsing returned minimal data"

        # Create DB record
        yield status_event("saving", "Saving to database...").to_sse()
        doc = ResumeDocument(
            filename=file.filename,
            storage_key=storage_key,
            content_type=file.content_type,
            file_size=file_size,
            status=doc_status,
            parsed_data=parsed_data,
            error_message=error_message,
        )
        result = await mongodb_client.resumes.insert_one(
            doc.model_dump(by_alias=True, exclude={"id"})
        )
        doc_id = str(result.inserted_id)

        logger.info(f"Resume uploaded: {file.filename} -> {doc_id} (status: {doc_status})")

        # Final result event with full response
        yield result_event("upload_complete", {
            "id": doc_id,
            "filename": file.filename,
            "status": doc_status,
            "message": f"Resume uploaded and {'parsed successfully' if doc_status == 'parsed' else 'parsing failed'}",
            "parsed_data": parsed_data.model_dump() if parsed_data and hasattr(parsed_data, "model_dump") else None,
        }).to_sse()
        yield done_event("Resume upload complete").to_sse()

    return EventSourceResponse(_stream_resume_upload())


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

@router.post("/job-descriptions")
async def create_job_description(
    request: JobDescriptionCreateRequest,
    user: AuthenticatedUser = Depends(require_permission(Permissions.UPLOAD_DOCUMENT)),
):
    """
    Create a new job description from text for matching.

    Returns an SSE stream with progress events and the final parsed result.
    """
    async def _stream_jd_create() -> AsyncIterator[dict]:
        from src.services.document_processor import DocumentProcessor

        processor = DocumentProcessor()

        # Stream LLM parsing
        parsed_data = None
        async for item in processor.parse_jd_with_llm_stream(request.description):
            if isinstance(item, StreamEvent):
                yield item.to_sse()
            elif isinstance(item, ParsedJobDescription):
                parsed_data = item

        # Determine final values
        if parsed_data:
            final_title = request.title if request.title else (parsed_data.title or "Untitled Position")
            final_company = request.company if request.company else parsed_data.company
            parsed_data.title = final_title
            parsed_data.company = final_company
            doc_status = "parsed"
            error_message = None
        else:
            final_title = request.title or "Untitled Position"
            final_company = request.company
            doc_status = "failed"
            error_message = "Failed to parse job description"

        # Save to database
        yield status_event("saving", "Saving to database...").to_sse()
        doc = JobDescriptionDocument(
            title=final_title,
            company=final_company,
            parsed_data=parsed_data,
            status=doc_status,
            error_message=error_message,
        )
        doc_dict = doc.model_dump(by_alias=True, exclude={"id"})
        doc_dict["raw_text"] = request.description

        result = await mongodb_client.job_descriptions.insert_one(doc_dict)
        doc_id = str(result.inserted_id)

        logger.info(f"Job description created: {final_title} -> {doc_id} (status: {doc_status})")

        yield result_event("upload_complete", {
            "id": doc_id,
            "title": final_title,
            "company": final_company,
            "status": doc_status,
            "parsed_data": parsed_data.model_dump() if parsed_data and hasattr(parsed_data, "model_dump") else None,
        }).to_sse()
        yield done_event("Job description creation complete").to_sse()

    return EventSourceResponse(_stream_jd_create())


@router.post("/job-descriptions/upload")
async def upload_job_description(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    company: Optional[str] = Form(None),
    storage: StorageClient = Depends(get_storage),
    user: AuthenticatedUser = Depends(require_permission(Permissions.UPLOAD_DOCUMENT)),
):
    """
    Upload a job description file (PDF/DOCX) for parsing and analysis.

    Returns an SSE stream with progress events and the final parsed result.

    Supported formats: PDF, DOC, DOCX
    Max file size: 10 MB
    """
    from src.services.document_processor import DocumentProcessor

    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Allowed types: PDF, DOC, DOCX"
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File too large. Maximum size: 10 MB"
        )

    async def _stream_jd_upload() -> AsyncIterator[dict]:
        processor = DocumentProcessor()

        # Upload to storage
        yield status_event("uploading", "Uploading file to storage...").to_sse()
        try:
            storage_key = await storage.upload_bytes(
                data=content,
                filename=file.filename,
                category="job_descriptions",
                content_type=file.content_type,
            )
        except Exception as e:
            yield error_event("uploading", f"Storage upload failed: {e}").to_sse()
            return

        # Extract text
        yield status_event("extracting", "Extracting text from document...").to_sse()
        try:
            raw_text = await processor.extract_text(content, file.content_type)
            yield progress_event(
                "extracting",
                f"Extracted {len(raw_text)} characters",
                chars=len(raw_text),
            ).to_sse()
        except Exception as e:
            yield error_event("extracting", f"Text extraction failed: {e}").to_sse()
            doc = JobDescriptionDocument(
                title=title or file.filename,
                company=company,
                filename=file.filename,
                storage_key=storage_key,
                content_type=file.content_type,
                file_size=file_size,
                status="failed",
                error_message=str(e),
            )
            doc_dict = doc.model_dump(by_alias=True, exclude={"id"})
            result = await mongodb_client.job_descriptions.insert_one(doc_dict)
            yield result_event("upload_record", {
                "id": str(result.inserted_id),
                "filename": file.filename,
                "status": "failed",
            }).to_sse()
            return

        # Stream LLM parsing
        parsed_data = None
        async for item in processor.parse_jd_with_llm_stream(raw_text):
            if isinstance(item, StreamEvent):
                yield item.to_sse()
            elif isinstance(item, ParsedJobDescription):
                parsed_data = item

        # Determine final values
        if parsed_data:
            final_title = title if title and title.strip() else (parsed_data.title or file.filename)
            final_company = company if company and company.strip() else parsed_data.company
            parsed_data.title = final_title
            parsed_data.company = final_company
            doc_status = "parsed"
            error_message = None
        else:
            final_title = title if title and title.strip() else file.filename
            final_company = company if company and company.strip() else None
            doc_status = "failed"
            error_message = "Failed to parse job description"

        # Save to database
        yield status_event("saving", "Saving to database...").to_sse()
        doc = JobDescriptionDocument(
            title=final_title,
            company=final_company,
            filename=file.filename,
            storage_key=storage_key,
            content_type=file.content_type,
            file_size=file_size,
            parsed_data=parsed_data,
            status=doc_status,
            error_message=error_message,
        )
        doc_dict = doc.model_dump(by_alias=True, exclude={"id"})
        if parsed_data:
            doc_dict["raw_text"] = parsed_data.raw_text

        result = await mongodb_client.job_descriptions.insert_one(doc_dict)
        doc_id = str(result.inserted_id)

        logger.info(f"Job description uploaded: {file.filename} -> {doc_id} (status: {doc_status})")

        yield result_event("upload_complete", {
            "id": doc_id,
            "title": final_title,
            "company": final_company,
            "filename": file.filename,
            "status": doc_status,
            "message": f"Job description uploaded and {'parsed successfully' if doc_status == 'parsed' else 'parsing failed'}",
            "parsed_data": parsed_data.model_dump() if parsed_data and hasattr(parsed_data, "model_dump") else None,
        }).to_sse()
        yield done_event("Job description upload complete").to_sse()

    return EventSourceResponse(_stream_jd_upload())


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

@router.post("/match")
async def match_resume_to_job(
    resume_id: str,
    job_description_id: str,
    use_llm: bool = True,
    user: AuthenticatedUser = Depends(require_permission(Permissions.RUN_ANALYSIS)),
):
    """
    Match a resume against a job description.

    Returns an SSE stream with progress events and the final match result.

    Args:
        resume_id: ID of the uploaded resume
        job_description_id: ID of the job description
        use_llm: Enable LLM qualitative sidecar (default True).
    """
    # Validate inputs upfront (before entering SSE stream)
    try:
        resume = await mongodb_client.resumes.find_one({"_id": ObjectId(resume_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resume ID")

    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    try:
        jd = await mongodb_client.job_descriptions.find_one({"_id": ObjectId(job_description_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job description ID")

    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")

    if resume.get("status") != "parsed" or jd.get("status") != "parsed":
        raise HTTPException(
            status_code=400,
            detail="Both resume and job description must be parsed before matching"
        )

    resume_parsed = resume.get("parsed_data")
    jd_parsed = jd.get("parsed_data")

    if not resume_parsed or not jd_parsed:
        raise HTTPException(
            status_code=400,
            detail="Parsed data missing from one or both documents. Please re-upload."
        )

    async def _stream_match() -> AsyncIterator[dict]:
        from src.services.semantic_matcher import get_semantic_matcher

        parsed_resume = ParsedResume(**resume_parsed)
        parsed_jd = ParsedJobDescription(**jd_parsed)

        yield status_event("matching", "Starting resume-JD matching...").to_sse()

        matcher = get_semantic_matcher()

        # Use streaming match if available, otherwise fall back to sync
        if hasattr(matcher, "match_stream"):
            async for item in matcher.match_stream(
                resume=parsed_resume,
                job_description=parsed_jd,
                resume_id=resume_id,
                job_description_id=job_description_id,
                use_llm=use_llm,
            ):
                if isinstance(item, StreamEvent):
                    yield item.to_sse()
                else:
                    # Final MatchResult
                    yield result_event("match_complete", {
                        "match_result": item.model_dump() if hasattr(item, "model_dump") else item,
                    }).to_sse()
        else:
            # Fallback: non-streaming match with wrapper events
            yield status_event("matching", "Computing embeddings and scores...").to_sse()
            match_result = await matcher.match(
                resume=parsed_resume,
                job_description=parsed_jd,
                resume_id=resume_id,
                job_description_id=job_description_id,
                use_llm=use_llm,
            )
            yield result_event("match_complete", {
                "match_result": match_result.model_dump() if hasattr(match_result, "model_dump") else match_result,
            }).to_sse()

        yield done_event("Matching complete").to_sse()

    return EventSourceResponse(_stream_match())
