"""
AI Interviewer - Gradio Frontend Application.

A standalone web application that acts as a pure API client to the backend.
"""
import gradio as gr
import asyncio
import base64
import json
import tempfile
import os
from typing import Optional, Tuple, List, Any
from api_client import api_client, UserRole, AuthState


# ==================== Helper Functions ====================

def run_async(coro):
    """Run an async coroutine in a sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def format_json(data: Any) -> str:
    """Format data as pretty JSON."""
    return json.dumps(data, indent=2, default=str)


def get_role_tabs(role: Optional[UserRole]) -> dict:
    """Get which tabs should be visible for a role."""
    if not role:
        return {
            "documents": False,
            "interviews": False,
            "live_session": False,
            "reports": False,
            "admin": False,
        }
    
    role_permissions = {
        UserRole.ADMIN: {
            "documents": True,
            "interviews": True,
            "live_session": True,
            "reports": True,
            "admin": True,
        },
        UserRole.HIRING_MANAGER: {
            "documents": True,
            "interviews": True,
            "live_session": True,
            "reports": True,
            "admin": False,
        },
        UserRole.INTERVIEWER: {
            "documents": False,
            "interviews": True,
            "live_session": True,
            "reports": False,
            "admin": False,
        },
        UserRole.CANDIDATE: {
            "documents": False,
            "interviews": False,
            "live_session": True,
            "reports": False,
            "admin": False,
        },
    }
    return role_permissions.get(role, role_permissions[UserRole.CANDIDATE])


# ==================== Auth Functions ====================

def login(role_str: str, user_id: str) -> Tuple[str, str, str]:
    """Login with a selected role."""
    if not user_id.strip():
        user_id = f"test-user-{role_str}"
    
    role = UserRole(role_str)
    token = api_client.login_with_role(role, user_id)
    
    status = f"Logged in as {role.value.replace('_', ' ').title()} ({user_id})"
    tabs = get_role_tabs(role)
    tab_info = ", ".join([k for k, v in tabs.items() if v])
    
    return status, token, f"Available tabs: {tab_info}"


def logout() -> Tuple[str, str, str]:
    """Logout and clear auth state."""
    api_client.logout()
    return "Not logged in", "", "Please login to access features"


def check_connection() -> str:
    """Check connection to backend."""
    result = run_async(api_client.health_check())
    if result.get("status") == "healthy":
        return f"Connected to backend: {api_client.base_url}"
    return f"Connection failed: {result}"


# ==================== Documents Functions ====================

def upload_resume(file) -> str:
    """Upload a resume file and display parsed data."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if file is None:
        return "Error: No file selected"
    
    result = run_async(api_client.upload_resume(file.name, os.path.basename(file.name)))
    
    # Format the result nicely if parsing succeeded
    if result.get("status") == "parsed" and result.get("parsed_data"):
        pd = result["parsed_data"]
        contact = pd.get("contact", {})
        
        output = []
        output.append(f"Resume ID: {result.get('id')}")
        output.append(f"Status: {result.get('status')}")
        output.append(f"File: {result.get('filename')}")
        output.append("")
        output.append("=== PARSED DATA ===")
        
        if contact:
            output.append(f"\nName: {contact.get('name', 'N/A')}")
            output.append(f"Email: {contact.get('email', 'N/A')}")
            output.append(f"Phone: {contact.get('phone', 'N/A')}")
            if contact.get('location'):
                output.append(f"Location: {contact.get('location')}")
            if contact.get('linkedin'):
                output.append(f"LinkedIn: {contact.get('linkedin')}")
            if contact.get('github'):
                output.append(f"GitHub: {contact.get('github')}")
        
        if pd.get("summary"):
            output.append(f"\nSummary: {pd.get('summary')[:200]}...")
        
        skills = pd.get("skills", [])
        if skills:
            output.append(f"\nSkills ({len(skills)}): {', '.join(skills[:15])}")
            if len(skills) > 15:
                output.append(f"  ...and {len(skills) - 15} more")
        
        experience = pd.get("experience", [])
        if experience:
            output.append(f"\nExperience ({len(experience)} positions):")
            for exp in experience[:3]:
                title = exp.get("title", "Unknown")
                company = exp.get("company", "Unknown")
                dates = f"{exp.get('start_date', '?')} - {exp.get('end_date', 'Present')}"
                output.append(f"  - {title} at {company} ({dates})")
        
        education = pd.get("education", [])
        if education:
            output.append(f"\nEducation ({len(education)}):")
            for edu in education[:2]:
                degree = edu.get("degree", "")
                field = edu.get("field", "")
                institution = edu.get("institution", "Unknown")
                output.append(f"  - {degree} {field} - {institution}")
        
        certifications = pd.get("certifications", [])
        if certifications:
            output.append(f"\nCertifications: {', '.join(certifications[:5])}")
        
        return "\n".join(output)
    
    # Fall back to JSON for errors or pending status
    return format_json(result)


def list_resumes() -> str:
    """List all resumes with status and parsed info."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    
    result = run_async(api_client.list_resumes())
    
    if "error" in result:
        return format_json(result)
    
    resumes = result.get("resumes", [])
    if not resumes:
        return "No resumes found."
    
    output = [f"Found {len(resumes)} resume(s):\n"]
    
    for r in resumes:
        output.append(f"ID: {r.get('_id')}")
        output.append(f"  File: {r.get('filename')}")
        output.append(f"  Status: {r.get('status', 'unknown')}")
        
        parsed = r.get("parsed_data")
        if parsed and r.get("status") == "parsed":
            contact = parsed.get("contact", {})
            name = contact.get("name", "Unknown")
            skills = parsed.get("skills", [])
            output.append(f"  Candidate: {name}")
            if skills:
                output.append(f"  Skills: {', '.join(skills[:8])}{'...' if len(skills) > 8 else ''}")
        elif r.get("error_message"):
            output.append(f"  Error: {r.get('error_message')[:50]}...")
        
        output.append("")
    
    return "\n".join(output)


def delete_resume(resume_id: str) -> str:
    """Delete a resume."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if not resume_id.strip():
        return "Error: Resume ID required"
    
    result = run_async(api_client.delete_resume(resume_id.strip()))
    return format_json(result)


def create_jd(title: str, company: str, description: str) -> str:
    """Create a job description."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if not all([title.strip(), company.strip(), description.strip()]):
        return "Error: All fields required"
    
    result = run_async(api_client.create_job_description(title, company, description))
    return format_json(result)


def upload_jd(file, title: str, company: str) -> str:
    """Upload a job description PDF/DOCX file."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if file is None:
        return "Error: No file selected"
    
    # Title and company are optional - will be extracted from PDF if not provided
    result = run_async(api_client.upload_job_description(
        file.name,
        os.path.basename(file.name),
        title=title if title and title.strip() else None,
        company=company if company and company.strip() else None,
    ))
    return format_json(result)


def list_jds() -> str:
    """List all job descriptions."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    
    result = run_async(api_client.list_job_descriptions())
    return format_json(result)


def match_documents(resume_id: str, jd_id: str) -> str:
    """Match resume to job description."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if not resume_id.strip() or not jd_id.strip():
        return "Error: Both Resume ID and JD ID required"
    
    result = run_async(api_client.match_resume_to_jd(resume_id.strip(), jd_id.strip()))
    return format_json(result)


# ==================== Interview Functions ====================

def start_interview(
    resume_id: str,
    jd_id: str,
    screening: int,
    technical: int,
    behavioral: int,
    system_design: int,
    difficulty: str,
) -> str:
    """Start a new interview session."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if not resume_id.strip() or not jd_id.strip():
        return "Error: Resume ID and JD ID required"
    
    result = run_async(api_client.start_interview(
        resume_id.strip(),
        jd_id.strip(),
        screening_questions=int(screening),
        technical_questions=int(technical),
        behavioral_questions=int(behavioral),
        system_design_questions=int(system_design),
        difficulty=difficulty,
    ))
    return format_json(result)


def list_sessions(status_filter: str) -> str:
    """List interview sessions."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    
    status = status_filter if status_filter != "all" else None
    result = run_async(api_client.list_sessions(status=status))
    return format_json(result)


def get_session_details(session_id: str) -> str:
    """Get session details."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if not session_id.strip():
        return "Error: Session ID required"
    
    result = run_async(api_client.get_session(session_id.strip()))
    return format_json(result)


# ==================== Live Session Functions ====================

current_session_id = None


def load_session(session_id: str) -> Tuple[str, str, str]:
    """Load a session for the live interview."""
    global current_session_id
    
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated", "", ""
    if not session_id.strip():
        return "Error: Session ID required", "", ""
    
    current_session_id = session_id.strip()
    result = run_async(api_client.get_session(current_session_id))
    
    if "error" in result:
        return f"Error: {result['error']}", "", ""
    
    # Extract current question
    current_q = result.get("current_question") or {}
    question_text = current_q.get("question_text", "No question available")
    question_stage = current_q.get("stage", "unknown")
    
    status = result.get("status", "unknown")
    progress = f"Question {result.get('current_question_index', 0) + 1} of {result.get('total_questions', 0)}"
    
    session_info = f"Session: {current_session_id}\nStatus: {status}\n{progress}"
    
    return session_info, f"[{question_stage.upper()}]\n\n{question_text}", ""


def refresh_session() -> Tuple[str, str]:
    """Refresh current session status."""
    global current_session_id
    
    if not current_session_id:
        return "No session loaded", ""
    
    result = run_async(api_client.get_session(current_session_id))
    
    if "error" in result:
        return f"Error: {result['error']}", ""
    
    current_q = result.get("current_question") or {}
    question_text = current_q.get("question_text", "No question available")
    question_stage = current_q.get("stage", "unknown")
    
    status = result.get("status", "unknown")
    progress = f"Question {result.get('current_question_index', 0) + 1} of {result.get('total_questions', 0)}"
    
    session_info = f"Session: {current_session_id}\nStatus: {status}\n{progress}"
    
    return session_info, f"[{question_stage.upper()}]\n\n{question_text}"


def submit_text_answer(answer: str) -> Tuple[str, str, str]:
    """Submit a text answer."""
    global current_session_id
    
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated", "", ""
    if not current_session_id:
        return "Error: No session loaded", "", ""
    if not answer.strip():
        return "Error: Answer required", "", ""
    
    result = run_async(api_client.submit_answer(current_session_id, answer_text=answer.strip()))
    
    if "error" in result:
        return f"Error: {result['error']}", "", ""
    
    # Get evaluation feedback
    evaluation = result.get("evaluation", {})
    scores = evaluation.get("scores", {})
    score = scores.get("overall", "N/A")
    strengths = evaluation.get("strengths", [])
    improvements = evaluation.get("improvements", [])
    
    feedback_parts = []
    if strengths:
        feedback_parts.append("Strengths:\n" + "\n".join(f"  - {s}" for s in strengths))
    if improvements:
        feedback_parts.append("Areas to improve:\n" + "\n".join(f"  - {i}" for i in improvements))
    feedback = "\n\n".join(feedback_parts) if feedback_parts else "No feedback"
    
    eval_text = f"Score: {score}/10\n\n{feedback}"
    
    # Refresh to get next question
    session_info, question = refresh_session()
    
    return session_info, question, eval_text


def submit_audio_answer(audio) -> Tuple[str, str, str]:
    """Submit an audio answer."""
    global current_session_id
    
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated", "", ""
    if not current_session_id:
        return "Error: No session loaded", "", ""
    if audio is None:
        return "Error: No audio recorded", "", ""
    
    # Read audio file and convert to base64
    sample_rate, audio_data = audio
    
    # Save to temp file as WAV
    import wave
    import numpy as np
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name
        with wave.open(temp_path, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            audio_array = np.array(audio_data, dtype=np.int16)
            wav_file.writeframes(audio_array.tobytes())
        
        with open(temp_path, 'rb') as f:
            audio_bytes = f.read()
        
        os.unlink(temp_path)
    
    audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
    
    result = run_async(api_client.submit_answer(current_session_id, answer_audio_base64=audio_base64))
    
    if "error" in result:
        return f"Error: {result['error']}", "", ""
    
    evaluation = result.get("evaluation", {})
    scores = evaluation.get("scores", {})
    score = scores.get("overall", "N/A")
    strengths = evaluation.get("strengths", [])
    improvements = evaluation.get("improvements", [])
    
    feedback_parts = []
    if strengths:
        feedback_parts.append("Strengths:\n" + "\n".join(f"  - {s}" for s in strengths))
    if improvements:
        feedback_parts.append("Areas to improve:\n" + "\n".join(f"  - {i}" for i in improvements))
    feedback = "\n\n".join(feedback_parts) if feedback_parts else "No feedback"
    
    eval_text = f"Score: {score}/10\n\n{feedback}"
    
    session_info, question = refresh_session()
    
    return session_info, question, eval_text


def play_question_tts() -> Optional[str]:
    """Get TTS audio for current question."""
    global current_session_id
    
    if not current_session_id:
        return None
    
    result = run_async(api_client.get_session(current_session_id))
    if "error" in result:
        return None
    
    question_text = (result.get("current_question") or {}).get("question_text", "")
    if not question_text:
        return None
    
    audio_bytes = run_async(api_client.text_to_speech(question_text))
    if not audio_bytes:
        return None
    
    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        return f.name


def end_current_interview(reason: str) -> str:
    """End the current interview."""
    global current_session_id
    
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if not current_session_id:
        return "Error: No session loaded"
    
    result = run_async(api_client.end_interview(current_session_id, reason=reason if reason.strip() else None))
    return format_json(result)


def pause_current_interview() -> str:
    """Pause the current interview."""
    global current_session_id
    
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if not current_session_id:
        return "Error: No session loaded"
    
    result = run_async(api_client.pause_interview(current_session_id))
    return format_json(result)


def resume_current_interview() -> str:
    """Resume the current interview."""
    global current_session_id
    
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if not current_session_id:
        return "Error: No session loaded"
    
    result = run_async(api_client.resume_interview(current_session_id))
    return format_json(result)


# ==================== Reports Functions ====================

def get_report(session_id: str) -> str:
    """Get interview report."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    if not session_id.strip():
        return "Error: Session ID required"
    
    result = run_async(api_client.get_report(session_id.strip()))
    return format_json(result)


def download_pdf_report(session_id: str) -> Optional[str]:
    """Download PDF report."""
    if not api_client.auth.is_authenticated:
        return None
    if not session_id.strip():
        return None
    
    pdf_bytes = run_async(api_client.download_pdf(session_id.strip()))
    if not pdf_bytes:
        return None
    
    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        return f.name


def list_reports_fn() -> str:
    """List all reports."""
    if not api_client.auth.is_authenticated:
        return "Error: Not authenticated"
    
    result = run_async(api_client.list_reports())
    return format_json(result)


# ==================== Admin Functions ====================

def admin_health_check() -> str:
    """Detailed health check."""
    result = run_async(api_client.health_detailed())
    return format_json(result)


def generate_token(role_str: str, user_id: str, session_id: str, expires_mins: int) -> str:
    """Generate a JWT token."""
    if not user_id.strip():
        user_id = f"generated-user-{role_str}"
    
    role = UserRole(role_str)
    token = api_client.generate_token(
        role,
        user_id.strip(),
        session_id=session_id.strip() if session_id.strip() else None,
        expires_minutes=int(expires_mins),
    )
    return token


# ==================== Build UI ====================

def create_app():
    """Create the Gradio application."""
    
    with gr.Blocks(title="AI Interviewer", theme=gr.themes.Default()) as app:
        gr.Markdown("# AI Interviewer System")
        gr.Markdown("Autonomous AI-powered technical and behavioral interviews")
        
        # ==================== Login Panel ====================
        with gr.Row():
            with gr.Column(scale=2):
                gr.Markdown("### Login")
                role_dropdown = gr.Dropdown(
                    choices=["admin", "hiring_manager", "interviewer", "candidate"],
                    value="admin",
                    label="Select Role",
                )
                user_id_input = gr.Textbox(
                    label="User ID (optional)",
                    placeholder="Leave empty for auto-generated",
                )
                with gr.Row():
                    login_btn = gr.Button("Login", variant="primary")
                    logout_btn = gr.Button("Logout")
                    check_btn = gr.Button("Check Connection")
            
            with gr.Column(scale=3):
                login_status = gr.Textbox(label="Status", value="Not logged in", interactive=False)
                current_token = gr.Textbox(label="Current Token", interactive=False, max_lines=3)
                tabs_info = gr.Textbox(label="Available Features", interactive=False)
        
        login_btn.click(
            login,
            inputs=[role_dropdown, user_id_input],
            outputs=[login_status, current_token, tabs_info],
        )
        logout_btn.click(logout, outputs=[login_status, current_token, tabs_info])
        check_btn.click(check_connection, outputs=[login_status])
        
        gr.Markdown("---")
        
        # ==================== Tabs ====================
        with gr.Tabs():
            
            # ==================== Documents Tab ====================
            with gr.Tab("Documents"):
                gr.Markdown("### Document Management")
                gr.Markdown("Upload resumes, create job descriptions, and match candidates.")
                
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### Upload Resume")
                        resume_file = gr.File(label="Resume (PDF/DOCX)", file_types=[".pdf", ".docx", ".doc"])
                        upload_btn = gr.Button("Upload Resume", variant="primary")
                        upload_result = gr.Textbox(label="Result", lines=15)
                        
                        upload_btn.click(upload_resume, inputs=[resume_file], outputs=[upload_result])
                    
                    with gr.Column():
                        gr.Markdown("#### Create Job Description")
                        
                        with gr.Tabs():
                            with gr.Tab("Upload PDF"):
                                jd_file = gr.File(label="Job Description (PDF/DOCX)", file_types=[".pdf", ".docx", ".doc"])
                                jd_upload_title = gr.Textbox(
                                    label="Job Title (optional)",
                                    placeholder="Leave empty to extract from PDF",
                                )
                                jd_upload_company = gr.Textbox(
                                    label="Company (optional)",
                                    placeholder="Leave empty to extract from PDF",
                                )
                                upload_jd_btn = gr.Button("Upload & Parse JD", variant="primary")
                                jd_upload_result = gr.Textbox(label="Result", lines=8)
                                
                                upload_jd_btn.click(
                                    upload_jd,
                                    inputs=[jd_file, jd_upload_title, jd_upload_company],
                                    outputs=[jd_upload_result],
                                )
                            
                            with gr.Tab("Enter Manually"):
                                jd_title = gr.Textbox(label="Job Title", placeholder="Senior Python Developer")
                                jd_company = gr.Textbox(label="Company", placeholder="TechCorp Inc")
                                jd_description = gr.Textbox(
                                    label="Description",
                                    lines=5,
                                    placeholder="We are looking for...",
                                )
                                create_jd_btn = gr.Button("Create JD")
                                jd_result = gr.Textbox(label="Result", lines=5)
                                
                                create_jd_btn.click(
                                    create_jd,
                                    inputs=[jd_title, jd_company, jd_description],
                                    outputs=[jd_result],
                                )
                
                gr.Markdown("---")
                
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### List Documents")
                        list_resumes_btn = gr.Button("List Resumes")
                        resumes_output = gr.Textbox(label="Resumes", lines=10)
                        list_resumes_btn.click(list_resumes, outputs=[resumes_output])
                        
                        list_jds_btn = gr.Button("List Job Descriptions")
                        jds_output = gr.Textbox(label="Job Descriptions", lines=10)
                        list_jds_btn.click(list_jds, outputs=[jds_output])
                    
                    with gr.Column():
                        gr.Markdown("#### Match / Delete")
                        match_resume_id = gr.Textbox(label="Resume ID")
                        match_jd_id = gr.Textbox(label="JD ID")
                        match_btn = gr.Button("Match Resume to JD")
                        match_result = gr.Textbox(label="Match Result", lines=5)
                        match_btn.click(
                            match_documents,
                            inputs=[match_resume_id, match_jd_id],
                            outputs=[match_result],
                        )
                        
                        delete_resume_id = gr.Textbox(label="Resume ID to Delete")
                        delete_btn = gr.Button("Delete Resume", variant="stop")
                        delete_result = gr.Textbox(label="Delete Result")
                        delete_btn.click(
                            delete_resume,
                            inputs=[delete_resume_id],
                            outputs=[delete_result],
                        )
            
            # ==================== Interviews Tab ====================
            with gr.Tab("Interviews"):
                gr.Markdown("### Interview Session Management")
                
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### Start New Interview")
                        int_resume_id = gr.Textbox(label="Resume ID")
                        int_jd_id = gr.Textbox(label="Job Description ID")
                        
                        with gr.Row():
                            screening_q = gr.Number(label="Screening Qs", value=2, minimum=0, maximum=5)
                            technical_q = gr.Number(label="Technical Qs", value=3, minimum=0, maximum=10)
                        with gr.Row():
                            behavioral_q = gr.Number(label="Behavioral Qs", value=2, minimum=0, maximum=5)
                            system_design_q = gr.Number(label="System Design Qs", value=1, minimum=0, maximum=3)
                        
                        difficulty_dd = gr.Dropdown(
                            choices=["easy", "medium", "hard"],
                            value="medium",
                            label="Difficulty",
                        )
                        
                        start_int_btn = gr.Button("Start Interview", variant="primary")
                        start_result = gr.Textbox(label="Result", lines=10)
                        
                        start_int_btn.click(
                            start_interview,
                            inputs=[
                                int_resume_id, int_jd_id,
                                screening_q, technical_q, behavioral_q, system_design_q,
                                difficulty_dd,
                            ],
                            outputs=[start_result],
                        )
                    
                    with gr.Column():
                        gr.Markdown("#### Session List")
                        status_filter = gr.Dropdown(
                            choices=["all", "active", "paused", "completed"],
                            value="all",
                            label="Status Filter",
                        )
                        list_sessions_btn = gr.Button("List Sessions")
                        sessions_output = gr.Textbox(label="Sessions", lines=15)
                        list_sessions_btn.click(
                            list_sessions,
                            inputs=[status_filter],
                            outputs=[sessions_output],
                        )
                        
                        gr.Markdown("#### Session Details")
                        detail_session_id = gr.Textbox(label="Session ID")
                        get_details_btn = gr.Button("Get Details")
                        details_output = gr.Textbox(label="Details", lines=10)
                        get_details_btn.click(
                            get_session_details,
                            inputs=[detail_session_id],
                            outputs=[details_output],
                        )
            
            # ==================== Live Session Tab ====================
            with gr.Tab("Live Session"):
                gr.Markdown("### Live Interview Session")
                gr.Markdown("Answer questions and receive real-time feedback.")
                
                with gr.Row():
                    session_id_input = gr.Textbox(label="Session ID", scale=3)
                    load_session_btn = gr.Button("Load Session", variant="primary")
                    refresh_btn = gr.Button("Refresh")
                
                with gr.Row():
                    with gr.Column(scale=2):
                        session_status = gr.Textbox(label="Session Status", lines=3, interactive=False)
                        current_question = gr.Textbox(label="Current Question", lines=6, interactive=False)
                        
                        gr.Markdown("#### Play Question (TTS)")
                        tts_btn = gr.Button("Play Question Audio")
                        tts_audio = gr.Audio(label="Question Audio", type="filepath")
                        tts_btn.click(play_question_tts, outputs=[tts_audio])
                    
                    with gr.Column(scale=2):
                        gr.Markdown("#### Submit Answer")
                        
                        with gr.Tab("Text Answer"):
                            text_answer = gr.Textbox(
                                label="Your Answer",
                                lines=8,
                                placeholder="Type your answer here...",
                            )
                            submit_text_btn = gr.Button("Submit Text Answer", variant="primary")
                        
                        with gr.Tab("Voice Answer"):
                            audio_answer = gr.Audio(
                                label="Record Answer",
                                sources=["microphone"],
                                type="numpy",
                            )
                            submit_audio_btn = gr.Button("Submit Audio Answer", variant="primary")
                        
                        evaluation_output = gr.Textbox(label="Evaluation Feedback", lines=6, interactive=False)
                
                load_session_btn.click(
                    load_session,
                    inputs=[session_id_input],
                    outputs=[session_status, current_question, evaluation_output],
                )
                refresh_btn.click(
                    refresh_session,
                    outputs=[session_status, current_question],
                )
                submit_text_btn.click(
                    submit_text_answer,
                    inputs=[text_answer],
                    outputs=[session_status, current_question, evaluation_output],
                )
                submit_audio_btn.click(
                    submit_audio_answer,
                    inputs=[audio_answer],
                    outputs=[session_status, current_question, evaluation_output],
                )
                
                gr.Markdown("---")
                
                with gr.Row():
                    pause_btn = gr.Button("Pause Interview")
                    resume_btn = gr.Button("Resume Interview")
                    end_reason = gr.Textbox(label="End Reason (optional)", scale=2)
                    end_btn = gr.Button("End Interview", variant="stop")
                
                control_output = gr.Textbox(label="Action Result", lines=3)
                
                pause_btn.click(pause_current_interview, outputs=[control_output])
                resume_btn.click(resume_current_interview, outputs=[control_output])
                end_btn.click(end_current_interview, inputs=[end_reason], outputs=[control_output])
            
            # ==================== Reports Tab ====================
            with gr.Tab("Reports"):
                gr.Markdown("### Interview Reports")
                gr.Markdown("View and download interview reports.")
                
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### Report List")
                        list_reports_btn = gr.Button("List All Reports")
                        reports_list = gr.Textbox(label="Reports", lines=10)
                        list_reports_btn.click(list_reports_fn, outputs=[reports_list])
                    
                    with gr.Column():
                        gr.Markdown("#### View Report")
                        report_session_id = gr.Textbox(label="Session ID")
                        
                        with gr.Row():
                            get_report_btn = gr.Button("Get JSON Report")
                            download_pdf_btn = gr.Button("Download PDF")
                        
                        report_json = gr.Textbox(label="Report (JSON)", lines=20)
                        pdf_download = gr.File(label="PDF Report")
                        
                        get_report_btn.click(
                            get_report,
                            inputs=[report_session_id],
                            outputs=[report_json],
                        )
                        download_pdf_btn.click(
                            download_pdf_report,
                            inputs=[report_session_id],
                            outputs=[pdf_download],
                        )
            
            # ==================== Admin Tab ====================
            with gr.Tab("Admin"):
                gr.Markdown("### Admin Tools")
                gr.Markdown("System health and token generation.")
                
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### System Health")
                        health_btn = gr.Button("Detailed Health Check")
                        health_output = gr.Textbox(label="Health Status", lines=15)
                        health_btn.click(admin_health_check, outputs=[health_output])
                    
                    with gr.Column():
                        gr.Markdown("#### Token Generator")
                        gen_role = gr.Dropdown(
                            choices=["admin", "hiring_manager", "interviewer", "candidate"],
                            value="admin",
                            label="Role",
                        )
                        gen_user_id = gr.Textbox(label="User ID", placeholder="user-123")
                        gen_session_id = gr.Textbox(label="Session ID (for candidate)", placeholder="Optional")
                        gen_expires = gr.Number(label="Expires (minutes)", value=60, minimum=1, maximum=1440)
                        gen_btn = gr.Button("Generate Token")
                        gen_token_output = gr.Textbox(label="Generated Token", lines=4)
                        
                        gen_btn.click(
                            generate_token,
                            inputs=[gen_role, gen_user_id, gen_session_id, gen_expires],
                            outputs=[gen_token_output],
                        )
        
        gr.Markdown("---")
        gr.Markdown("AI Interviewer System - HackGeniX | Backend: http://localhost:8000")
    
    return app


if __name__ == "__main__":
    app = create_app()
    app.launch(server_name="0.0.0.0", server_port=7860)
