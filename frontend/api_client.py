"""
API Client for AI Interviewer Backend.

Handles all HTTP requests with JWT authentication.
"""
import httpx
import jwt
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    HIRING_MANAGER = "hiring_manager"
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"


@dataclass
class AuthState:
    """Current authentication state."""
    token: Optional[str] = None
    role: Optional[UserRole] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    expires_at: Optional[int] = None
    
    @property
    def is_authenticated(self) -> bool:
        if not self.token or not self.expires_at:
            return False
        return time.time() < self.expires_at
    
    @property
    def role_display(self) -> str:
        if not self.role:
            return "Not logged in"
        return self.role.value.replace("_", " ").title()


class APIClient:
    """
    HTTP client for the AI Interviewer API.
    
    Handles JWT authentication and provides methods for all API endpoints.
    """
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.auth = AuthState()
        self._jwt_secret = "your-super-secret-key-change-in-production"  # Default from backend
    
    def set_jwt_secret(self, secret: str):
        """Set the JWT secret for token generation."""
        self._jwt_secret = secret
    
    def generate_token(
        self,
        role: UserRole,
        user_id: str,
        session_id: Optional[str] = None,
        expires_minutes: int = 60,
    ) -> str:
        """Generate a JWT token for testing."""
        now = int(time.time())
        payload = {
            "sub": user_id,
            "role": role.value,
            "iat": now,
            "exp": now + (expires_minutes * 60),
        }
        if session_id:
            payload["session_id"] = session_id
        
        token = jwt.encode(payload, self._jwt_secret, algorithm="HS256")
        return token
    
    def login_with_token(self, token: str) -> bool:
        """Login with an existing JWT token."""
        try:
            # Decode without verification to extract claims
            payload = jwt.decode(token, options={"verify_signature": False})
            
            self.auth = AuthState(
                token=token,
                role=UserRole(payload.get("role", "candidate")),
                user_id=payload.get("sub"),
                session_id=payload.get("session_id"),
                expires_at=payload.get("exp"),
            )
            return True
        except Exception as e:
            print(f"Token decode error: {e}")
            return False
    
    def login_with_role(
        self,
        role: UserRole,
        user_id: str,
        session_id: Optional[str] = None,
        expires_minutes: int = 60,
    ) -> str:
        """Generate a token and login."""
        token = self.generate_token(role, user_id, session_id, expires_minutes)
        self.login_with_token(token)
        return token
    
    def logout(self):
        """Clear authentication state."""
        self.auth = AuthState()
    
    @property
    def headers(self) -> Dict[str, str]:
        """Get headers with authorization if authenticated."""
        if self.auth.token:
            return {"Authorization": f"Bearer {self.auth.token}"}
        return {}
    
    # ==================== Health ====================
    
    async def health_check(self) -> Dict[str, Any]:
        """Check API health status."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(f"{self.base_url}/health")
                return response.json()
            except Exception as e:
                return {"status": "error", "error": str(e)}
    
    async def health_detailed(self) -> Dict[str, Any]:
        """Get detailed health status."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(f"{self.base_url}/health/detailed")
                return response.json()
            except Exception as e:
                return {"status": "error", "error": str(e)}
    
    # ==================== Documents ====================
    
    async def upload_resume(self, file_path: str, filename: str) -> Dict[str, Any]:
        """Upload a resume file. Includes LLM parsing which may take time."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(file_path, "rb") as f:
                files = {"file": (filename, f, "application/pdf")}
                response = await client.post(
                    f"{self.base_url}/api/v1/documents/resumes",
                    files=files,
                    headers=self.headers,
                )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def list_resumes(self, skip: int = 0, limit: int = 20) -> Dict[str, Any]:
        """List all resumes."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/documents/resumes",
                params={"skip": skip, "limit": limit},
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def get_resume(self, resume_id: str) -> Dict[str, Any]:
        """Get resume details."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/documents/resumes/{resume_id}",
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def delete_resume(self, resume_id: str) -> Dict[str, Any]:
        """Delete a resume."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(
                f"{self.base_url}/api/v1/documents/resumes/{resume_id}",
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def create_job_description(
        self,
        title: str,
        company: str,
        description: str,
    ) -> Dict[str, Any]:
        """Create a job description."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/documents/job-descriptions",
                json={"title": title, "company": company, "description": description},
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def upload_job_description(
        self,
        file_path: str,
        filename: str,
        title: Optional[str] = None,
        company: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload a job description file (PDF/DOCX) for parsing."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(file_path, "rb") as f:
                files = {"file": (filename, f, "application/pdf")}
                data = {}
                if title and title.strip():
                    data["title"] = title
                if company and company.strip():
                    data["company"] = company
                
                response = await client.post(
                    f"{self.base_url}/api/v1/documents/job-descriptions/upload",
                    files=files,
                    data=data if data else None,
                    headers=self.headers,
                )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def list_job_descriptions(self, skip: int = 0, limit: int = 20) -> Dict[str, Any]:
        """List all job descriptions."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/documents/job-descriptions",
                params={"skip": skip, "limit": limit},
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def get_job_description(self, jd_id: str) -> Dict[str, Any]:
        """Get job description details."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/documents/job-descriptions/{jd_id}",
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def match_resume_to_jd(self, resume_id: str, jd_id: str) -> Dict[str, Any]:
        """Match a resume against a job description."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/documents/match",
                params={"resume_id": resume_id, "job_description_id": jd_id},
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    # ==================== Sessions ====================
    
    async def start_interview(
        self,
        resume_id: str,
        jd_id: str,
        screening_questions: int = 2,
        technical_questions: int = 3,
        behavioral_questions: int = 2,
        system_design_questions: int = 1,
        difficulty: str = "medium",
    ) -> Dict[str, Any]:
        """Start a new interview session."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/sessions/start",
                json={
                    "resume_id": resume_id,
                    "job_description_id": jd_id,
                    "config": {
                        "screening_questions": screening_questions,
                        "technical_questions": technical_questions,
                        "behavioral_questions": behavioral_questions,
                        "system_design_questions": system_design_questions,
                        "difficulty": difficulty,
                    },
                },
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def list_sessions(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List interview sessions."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {"limit": limit}
            if status:
                params["status"] = status
            response = await client.get(
                f"{self.base_url}/api/v1/sessions/",
                params=params,
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return [{"error": response.text, "status_code": response.status_code}]
    
    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session details."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/sessions/{session_id}",
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def get_session_progress(self, session_id: str) -> Dict[str, Any]:
        """Get session progress."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/sessions/{session_id}/progress",
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def submit_answer(
        self,
        session_id: str,
        answer_text: Optional[str] = None,
        answer_audio_base64: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit an answer to the current question."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {"session_id": session_id}
            if answer_text:
                payload["answer_text"] = answer_text
            if answer_audio_base64:
                payload["answer_audio_base64"] = answer_audio_base64
            
            response = await client.post(
                f"{self.base_url}/api/v1/sessions/answer",
                json=payload,
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def pause_interview(self, session_id: str) -> Dict[str, Any]:
        """Pause an interview."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/sessions/{session_id}/pause",
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def resume_interview(self, session_id: str) -> Dict[str, Any]:
        """Resume a paused interview."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/sessions/{session_id}/resume",
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def end_interview(self, session_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """End an interview session."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {}
            if reason:
                payload["reason"] = reason
            response = await client.post(
                f"{self.base_url}/api/v1/sessions/{session_id}/end",
                json=payload if payload else None,
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    # ==================== Reports ====================
    
    async def get_report(self, session_id: str) -> Dict[str, Any]:
        """Get interview report as JSON."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/reports/{session_id}",
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def download_pdf(self, session_id: str) -> bytes:
        """Download interview report as PDF."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/reports/{session_id}/pdf",
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.content
            return b""
    
    async def list_reports(self, limit: int = 50) -> Dict[str, Any]:
        """List available reports."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/reports/",
                params={"limit": limit},
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    # ==================== Voice ====================
    
    async def text_to_speech(self, text: str) -> bytes:
        """Convert text to speech audio."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/voice/synthesize",
                json={"text": text},
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.content
            return b""
    
    async def speech_to_text(self, audio_data: bytes, filename: str = "audio.wav") -> Dict[str, Any]:
        """Convert speech audio to text."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"audio": (filename, audio_data, "audio/wav")}
            response = await client.post(
                f"{self.base_url}/api/v1/voice/transcribe",
                files=files,
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    # ==================== Questions ====================
    
    async def generate_questions(
        self,
        jd_id: str,
        resume_id: Optional[str] = None,
        stage: str = "technical",
        num_questions: int = 5,
        difficulty: str = "medium",
    ) -> Dict[str, Any]:
        """Generate interview questions."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "job_description_id": jd_id,
                "stage": stage,
                "num_questions": num_questions,
                "difficulty": difficulty,
            }
            if resume_id:
                payload["resume_id"] = resume_id
            
            response = await client.post(
                f"{self.base_url}/api/v1/questions/questions/generate",
                json=payload,
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}
    
    async def evaluate_answer(
        self,
        question: str,
        answer: str,
        stage: str = "technical",
    ) -> Dict[str, Any]:
        """Evaluate a candidate's answer."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/questions/answers/evaluate",
                json={
                    "question": question,
                    "answer": answer,
                    "stage": stage,
                },
                headers=self.headers,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text, "status_code": response.status_code}


# Global client instance
api_client = APIClient()
