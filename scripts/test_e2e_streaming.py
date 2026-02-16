#!/usr/bin/env python
"""
End-to-end streaming test against the deployed (or local) backend.

Tests the full interview lifecycle with SSE streaming verification:
  1. Health check
  2. Upload resume (SSE: status, token, progress, result, done)
  3. Create job description (SSE: status, token, result, done)
  4. Match resume to JD (SSE: status, token, result, done)
  5. Start interview session (SSE: status, token, result, done)
  6. Submit answer (SSE: status, token, result, done)
  7. Get session details (REST)
  8. End interview (REST)
  9. Get report (REST)
  10. Cleanup: delete resume, session

Usage:
    # Against Railway deployment:
    .venv\\Scripts\\python.exe scripts\\test_e2e_streaming.py

    # Against local backend:
    .venv\\Scripts\\python.exe scripts\\test_e2e_streaming.py --base-url http://localhost:8000

Environment variables:
    BACKEND_URL      - Backend base URL (default: http://localhost:8000)
    JWT_SECRET_KEY   - JWT signing secret (default: your-super-secret-key-change-in-production)
"""
import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
import jwt


# ============================================================
# Configuration
# ============================================================

DEFAULT_BASE_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
DEFAULT_JWT_SECRET = os.environ.get(
    "JWT_SECRET_KEY",
    os.environ.get("JWT_SECRET", "your-super-secret-key-change-in-production"),
)

# Minimal valid PDF (1-page blank) — avoids needing an external file or fpdf
MINIMAL_PDF = (
    b"%PDF-1.0\n"
    b"1 0 obj<</Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</MediaBox[0 0 612 792]>>endobj\n"
    b"trailer<</Root 1 0 R>>"
)

# Sample resume text embedded as a tiny "PDF" with text content.
# The backend extracts text from PDFs; a blank PDF yields empty text
# which makes the LLM return minimal data. Instead we use a DOCX-like
# plain-text approach: upload a .docx that's actually a raw-text file.
# FastAPI UploadFile + python-docx will fail on raw text, so we build
# a real minimal DOCX in memory.

SAMPLE_RESUME_TEXT = """
John Doe
Email: john.doe@example.com | Phone: +1-555-0100 | Location: San Francisco, CA
LinkedIn: linkedin.com/in/johndoe | GitHub: github.com/johndoe

SUMMARY
Senior Software Engineer with 6 years of experience in Python, FastAPI, and distributed systems.
Passionate about building scalable microservices and real-time data pipelines.

SKILLS
Python, FastAPI, Django, PostgreSQL, MongoDB, Redis, Docker, Kubernetes, AWS, CI/CD,
REST APIs, GraphQL, Machine Learning, TensorFlow, PyTorch, Git, Linux, Agile

EXPERIENCE

Senior Software Engineer | TechCorp Inc | San Francisco, CA | Jan 2021 - Present
- Designed and built a real-time data pipeline processing 10M events/day using Kafka and Flink
- Led migration from monolith to microservices architecture, reducing deployment time by 70%
- Mentored 4 junior engineers and established code review best practices
- Skills: Python, Kafka, Flink, Kubernetes, AWS

Software Engineer | DataFlow Systems | Austin, TX | Jun 2018 - Dec 2020
- Developed REST APIs serving 50K requests/minute using FastAPI and PostgreSQL
- Implemented automated testing pipeline achieving 95% code coverage
- Built real-time monitoring dashboard with WebSocket streaming
- Skills: Python, FastAPI, PostgreSQL, Docker, React

PROJECTS

Open Source Contribution - AsyncIO Task Scheduler (Python, asyncio)
- Built a distributed task scheduler with fault tolerance and retry logic
- 500+ GitHub stars, used in production by 3 companies

EDUCATION

B.S. Computer Science | University of California, Berkeley | 2014 - 2018 | GPA: 3.7

CERTIFICATIONS
AWS Solutions Architect Associate, Kubernetes Application Developer (CKAD)
"""

SAMPLE_JD_TEXT = """
Senior Python Developer

Company: InnovateTech Solutions

We are looking for a Senior Python Developer to join our backend engineering team.

Requirements:
- 5+ years of experience with Python
- Strong experience with FastAPI or Django
- Experience with PostgreSQL or MongoDB
- Familiarity with Docker and Kubernetes
- Experience with CI/CD pipelines
- Strong understanding of REST API design
- Experience with message queues (Kafka, RabbitMQ)

Responsibilities:
- Design and implement scalable backend services
- Lead code reviews and mentor junior developers
- Collaborate with product and frontend teams
- Write comprehensive tests and documentation
- Participate in on-call rotation

Nice to have:
- Experience with machine learning frameworks
- Contributions to open source projects
- AWS or GCP certifications

Benefits:
- Competitive salary ($150K-$200K)
- Remote-first culture
- Health, dental, vision insurance
- 401(k) matching
- Unlimited PTO
"""


# ============================================================
# Helpers
# ============================================================

@dataclass
class TestContext:
    """Holds IDs and state accumulated across test steps."""
    base_url: str = ""
    token: str = ""
    resume_id: Optional[str] = None
    jd_id: Optional[str] = None
    match_result: Optional[Dict] = None
    session_id: Optional[str] = None
    first_question: Optional[Dict] = None
    answer_result: Optional[Dict] = None
    report: Optional[Dict] = None


@dataclass
class SSEStats:
    """Accumulated stats from an SSE stream."""
    event_counts: Dict[str, int] = field(default_factory=dict)
    token_count: int = 0
    token_chars: int = 0
    stages_seen: List[str] = field(default_factory=list)
    result_stages: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    final_result: Optional[Dict] = None
    all_events: List[Tuple[str, Dict]] = field(default_factory=list)

    def record(self, event_type: str, data: dict):
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        self.all_events.append((event_type, data))

        stage = data.get("stage", "")
        if stage and stage not in self.stages_seen:
            self.stages_seen.append(stage)

        if event_type == "token":
            self.token_count += 1
            content = data.get("data", {}).get("content", "")
            self.token_chars += len(content)
        elif event_type == "result":
            self.result_stages.append(stage)
            self.final_result = data
        elif event_type == "error":
            self.errors.append(data.get("message", str(data)))

    def summary(self) -> str:
        parts = [f"events={dict(self.event_counts)}"]
        if self.token_count:
            parts.append(f"tokens={self.token_count} ({self.token_chars} chars)")
        parts.append(f"stages={self.stages_seen}")
        if self.result_stages:
            parts.append(f"result_stages={self.result_stages}")
        if self.errors:
            parts.append(f"ERRORS={self.errors}")
        return " | ".join(parts)


def generate_jwt(secret: str, role: str = "admin", user_id: str = "e2e-test-user") -> str:
    """Generate a JWT token for testing."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def build_minimal_docx(text: str) -> bytes:
    """Build a minimal .docx file in-memory from plain text.

    A .docx is a ZIP archive with XML inside. We create the bare
    minimum structure that python-docx / docx2txt can read on the
    backend.
    """
    import zipfile
    import io

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )

    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '</Relationships>'
    )

    # Build paragraphs from text lines
    paragraphs = []
    for line in text.strip().split("\n"):
        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        paragraphs.append(
            f'<w:p><w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>'
        )
    body = "".join(paragraphs)

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body}</w:body>'
        '</w:document>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
    return buf.getvalue()


async def parse_sse_stream(response: httpx.Response) -> SSEStats:
    """Parse an SSE stream and collect stats."""
    stats = SSEStats()
    current_event = "message"
    current_data_lines: list = []

    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\n").rstrip("\r")

        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current_data_lines.append(line[len("data:"):].strip())
        elif line.startswith(":"):
            continue
        elif line == "":
            if current_data_lines:
                data_str = "\n".join(current_data_lines)
                try:
                    data_dict = json.loads(data_str)
                except json.JSONDecodeError:
                    data_dict = {"raw": data_str}
                stats.record(current_event, data_dict)
            current_event = "message"
            current_data_lines = []

    # Trailing event
    if current_data_lines:
        data_str = "\n".join(current_data_lines)
        try:
            data_dict = json.loads(data_str)
        except json.JSONDecodeError:
            data_dict = {"raw": data_str}
        stats.record(current_event, data_dict)

    return stats


# ============================================================
# Test Steps
# ============================================================

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"
INFO = "[INFO]"


async def test_health(ctx: TestContext) -> bool:
    """Step 1: Health check."""
    print("\n" + "=" * 70)
    print("STEP 1: Health Check")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{ctx.base_url}/health")

    print(f"  Status: {resp.status_code}")
    data = resp.json()
    print(f"  Response: {json.dumps(data, indent=2)}")

    if resp.status_code != 200:
        print(f"  {FAIL} Health check returned {resp.status_code}")
        return False

    if data.get("status") not in ("healthy", "degraded"):
        print(f"  {FAIL} Unexpected status: {data.get('status')}")
        return False

    mongodb_ok = data.get("mongodb", False)
    storage_ok = data.get("storage", False)
    print(f"  MongoDB: {'OK' if mongodb_ok else 'DOWN'}")
    print(f"  Storage: {'OK' if storage_ok else 'DOWN'}")

    if not mongodb_ok:
        print(f"  {FAIL} MongoDB is down — cannot proceed")
        return False

    print(f"  {PASS} Backend is reachable and healthy")
    return True


async def test_upload_resume(ctx: TestContext) -> bool:
    """Step 2: Upload resume via SSE streaming endpoint."""
    print("\n" + "=" * 70)
    print("STEP 2: Upload Resume (SSE Streaming)")
    print("=" * 70)

    docx_bytes = build_minimal_docx(SAMPLE_RESUME_TEXT)
    print(f"  Generated DOCX: {len(docx_bytes)} bytes")

    headers = {"Authorization": f"Bearer {ctx.token}"}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
    ) as client:
        async with client.stream(
            "POST",
            f"{ctx.base_url}/api/v1/documents/resumes",
            headers=headers,
            files={
                "file": (
                    "john_doe_resume.docx",
                    docx_bytes,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        ) as response:
            if response.status_code != 200:
                await response.aread()
                print(f"  {FAIL} HTTP {response.status_code}: {response.text[:500]}")
                return False
            stats = await parse_sse_stream(response)

    print(f"  SSE: {stats.summary()}")

    # Assertions
    ok = True

    if stats.errors:
        print(f"  {FAIL} SSE errors: {stats.errors}")
        ok = False

    if "status" not in stats.event_counts:
        print(f"  {FAIL} No 'status' events received")
        ok = False
    else:
        print(f"  {PASS} Received {stats.event_counts['status']} status events")

    if stats.token_count == 0:
        print(f"  {WARN} No 'token' events — token-by-token streaming may not be working")
    else:
        print(f"  {PASS} Received {stats.token_count} token events ({stats.token_chars} chars)")

    if "done" not in stats.event_counts:
        print(f"  {FAIL} No 'done' event — stream may not have completed")
        ok = False
    else:
        print(f"  {PASS} Stream completed with 'done' event")

    if "upload_complete" not in stats.result_stages:
        print(f"  {FAIL} No 'upload_complete' result event")
        ok = False
    else:
        result_data = None
        for evt_type, evt_data in stats.all_events:
            if evt_type == "result" and evt_data.get("stage") == "upload_complete":
                result_data = evt_data.get("data", {})
                break

        if result_data:
            ctx.resume_id = result_data.get("id")
            status_val = result_data.get("status")
            parsed = result_data.get("parsed_data")

            print(f"  Resume ID: {ctx.resume_id}")
            print(f"  Parse status: {status_val}")

            if status_val == "parsed" and parsed:
                contact = parsed.get("contact", {})
                skills = parsed.get("skills", [])
                print(f"  Candidate: {contact.get('name', 'N/A')}")
                print(f"  Skills: {len(skills)} found")
                if skills:
                    print(f"    {', '.join(skills[:10])}{'...' if len(skills) > 10 else ''}")
                print(f"  {PASS} Resume parsed successfully")
            elif status_val == "parsed":
                print(f"  {WARN} Status is 'parsed' but parsed_data is empty")
            else:
                print(f"  {WARN} Parse status is '{status_val}' — LLM may have had trouble")
                ok = True  # Not fatal; the ID still works for subsequent steps
        else:
            print(f"  {FAIL} upload_complete event had no data")
            ok = False

    if not ctx.resume_id:
        print(f"  {FAIL} No resume ID obtained — cannot continue")
        return False

    if ok:
        print(f"  {PASS} Resume upload complete")
    return ok


async def test_create_jd(ctx: TestContext) -> bool:
    """Step 3: Create job description via SSE streaming endpoint."""
    print("\n" + "=" * 70)
    print("STEP 3: Create Job Description (SSE Streaming)")
    print("=" * 70)

    headers = {"Authorization": f"Bearer {ctx.token}"}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
    ) as client:
        async with client.stream(
            "POST",
            f"{ctx.base_url}/api/v1/documents/job-descriptions",
            headers=headers,
            json={
                "title": "Senior Python Developer",
                "company": "InnovateTech Solutions",
                "description": SAMPLE_JD_TEXT,
            },
        ) as response:
            if response.status_code != 200:
                await response.aread()
                print(f"  {FAIL} HTTP {response.status_code}: {response.text[:500]}")
                return False
            stats = await parse_sse_stream(response)

    print(f"  SSE: {stats.summary()}")

    ok = True

    if stats.errors:
        print(f"  {FAIL} SSE errors: {stats.errors}")
        ok = False

    if stats.token_count == 0:
        print(f"  {WARN} No token events for JD parsing")
    else:
        print(f"  {PASS} Received {stats.token_count} token events ({stats.token_chars} chars)")

    if "upload_complete" not in stats.result_stages:
        print(f"  {FAIL} No 'upload_complete' result event")
        ok = False
    else:
        for evt_type, evt_data in stats.all_events:
            if evt_type == "result" and evt_data.get("stage") == "upload_complete":
                result_data = evt_data.get("data", {})
                ctx.jd_id = result_data.get("id")
                print(f"  JD ID: {ctx.jd_id}")
                print(f"  Title: {result_data.get('title')}")
                print(f"  Status: {result_data.get('status')}")
                break

    if "done" in stats.event_counts:
        print(f"  {PASS} Stream completed")
    else:
        print(f"  {FAIL} No 'done' event")
        ok = False

    if not ctx.jd_id:
        print(f"  {FAIL} No JD ID obtained — cannot continue")
        return False

    if ok:
        print(f"  {PASS} Job description created")
    return ok


async def test_match(ctx: TestContext) -> bool:
    """Step 4: Match resume to JD via SSE streaming endpoint."""
    print("\n" + "=" * 70)
    print("STEP 4: Match Resume to JD (SSE Streaming)")
    print("=" * 70)

    headers = {"Authorization": f"Bearer {ctx.token}"}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
    ) as client:
        async with client.stream(
            "POST",
            f"{ctx.base_url}/api/v1/documents/match",
            headers=headers,
            params={
                "resume_id": ctx.resume_id,
                "job_description_id": ctx.jd_id,
            },
        ) as response:
            if response.status_code != 200:
                await response.aread()
                print(f"  {FAIL} HTTP {response.status_code}: {response.text[:500]}")
                return False
            stats = await parse_sse_stream(response)

    print(f"  SSE: {stats.summary()}")

    ok = True

    if stats.errors:
        print(f"  {FAIL} SSE errors: {stats.errors}")
        ok = False

    if stats.token_count == 0:
        print(f"  {WARN} No token events for matching LLM assessment")
    else:
        print(f"  {PASS} Received {stats.token_count} token events ({stats.token_chars} chars)")

    if "match_complete" not in stats.result_stages:
        print(f"  {FAIL} No 'match_complete' result event")
        ok = False
    else:
        for evt_type, evt_data in stats.all_events:
            if evt_type == "result" and evt_data.get("stage") == "match_complete":
                match_data = evt_data.get("data", {}).get("match_result", {})
                ctx.match_result = match_data

                overall = match_data.get("overall_score")
                skill_score = match_data.get("skill_match_score")
                matched = match_data.get("matched_skills", [])
                missing = match_data.get("missing_skills", [])

                print(f"  Overall score: {overall}")
                print(f"  Skill match score: {skill_score}")
                print(f"  Matched skills ({len(matched)}): {', '.join(matched[:8])}{'...' if len(matched) > 8 else ''}")
                print(f"  Missing skills ({len(missing)}): {', '.join(missing[:8])}{'...' if len(missing) > 8 else ''}")
                print(f"  {PASS} Match result received")
                break

    if "done" in stats.event_counts:
        print(f"  {PASS} Stream completed")
    else:
        print(f"  {FAIL} No 'done' event")
        ok = False

    if ok:
        print(f"  {PASS} Matching complete")
    return ok


async def test_start_interview(ctx: TestContext) -> bool:
    """Step 5: Start interview session via SSE streaming endpoint."""
    print("\n" + "=" * 70)
    print("STEP 5: Start Interview (SSE Streaming)")
    print("=" * 70)

    headers = {"Authorization": f"Bearer {ctx.token}"}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    ) as client:
        async with client.stream(
            "POST",
            f"{ctx.base_url}/api/v1/sessions/start",
            headers=headers,
            json={
                "resume_id": ctx.resume_id,
                "job_description_id": ctx.jd_id,
                "config": {
                    "screening_questions": 1,
                    "technical_questions": 1,
                    "behavioral_questions": 1,
                    "system_design_questions": 0,
                    "difficulty": "medium",
                },
            },
        ) as response:
            if response.status_code != 200:
                await response.aread()
                print(f"  {FAIL} HTTP {response.status_code}: {response.text[:500]}")
                return False
            stats = await parse_sse_stream(response)

    print(f"  SSE: {stats.summary()}")

    ok = True

    if stats.errors:
        print(f"  {FAIL} SSE errors: {stats.errors}")
        ok = False

    if stats.token_count == 0:
        print(f"  {WARN} No token events for question generation")
    else:
        print(f"  {PASS} Received {stats.token_count} token events ({stats.token_chars} chars)")

    # Extract session ID from interview_ready result event
    # (session_created is a status event with text message only)
    if "interview_ready" in stats.result_stages:
        for evt_type, evt_data in stats.all_events:
            if evt_type == "result" and evt_data.get("stage") == "interview_ready":
                ready_data = evt_data.get("data", {})
                ctx.session_id = ready_data.get("session_id")
                total_q = ready_data.get("total_questions", 0)
                first_q = ready_data.get("first_question")
                candidate = ready_data.get("candidate_name")
                role = ready_data.get("role_title")
                stages = ready_data.get("stages", {})

                print(f"  Session ID: {ctx.session_id}")
                print(f"  Candidate: {candidate}")
                print(f"  Role: {role}")
                print(f"  Total questions: {total_q}")
                print(f"  Stages: {stages}")
                if first_q:
                    ctx.first_question = first_q
                    q_stage = first_q.get("stage", "?")
                    q_text = first_q.get("question_text", "")[:100]
                    print(f"  First question [{q_stage}]: {q_text}...")
                print(f"  {PASS} Interview is ready")
                break
    else:
        # Maybe questions_ready came but not interview_ready
        if "questions_ready" in stats.result_stages:
            print(f"  {WARN} Got 'questions_ready' but not 'interview_ready'")
        else:
            print(f"  {FAIL} No interview_ready or questions_ready event")
            ok = False

    if "done" in stats.event_counts:
        print(f"  {PASS} Stream completed")

    if not ctx.session_id:
        print(f"  {FAIL} No session ID obtained — cannot continue")
        return False

    # If we didn't get the first question from the stream, fetch via REST
    if not ctx.first_question:
        print(f"  {INFO} Fetching session to get first question...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{ctx.base_url}/api/v1/sessions/{ctx.session_id}",
                headers=headers,
            )
            if resp.status_code == 200:
                session_data = resp.json()
                ctx.first_question = session_data.get("current_question")
                if ctx.first_question:
                    print(f"  First question: {ctx.first_question.get('question_text', '')[:100]}...")
                else:
                    print(f"  {WARN} No current_question in session data")

    if ok:
        print(f"  {PASS} Interview started")
    return ok


async def test_submit_answer(ctx: TestContext) -> bool:
    """Step 6: Submit an answer via SSE streaming endpoint."""
    print("\n" + "=" * 70)
    print("STEP 6: Submit Answer (SSE Streaming)")
    print("=" * 70)

    if not ctx.first_question:
        print(f"  {FAIL} No question to answer — skipping")
        return False

    q_text = ctx.first_question.get("question_text", "")
    print(f"  Question: {q_text[:120]}...")

    # Generate a reasonable answer
    answer = (
        "In my experience as a Senior Software Engineer at TechCorp, I have "
        "worked extensively with Python and FastAPI to build scalable microservices. "
        "For example, I designed a real-time data pipeline processing 10 million "
        "events per day using Kafka and Flink. I also led the migration from a "
        "monolithic architecture to microservices, which reduced our deployment "
        "time by 70%. I believe my experience with distributed systems, REST API "
        "design, and mentoring junior engineers aligns well with this role."
    )
    print(f"  Answer: {answer[:100]}...")

    headers = {"Authorization": f"Bearer {ctx.token}"}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)
    ) as client:
        async with client.stream(
            "POST",
            f"{ctx.base_url}/api/v1/sessions/answer",
            headers=headers,
            json={
                "session_id": ctx.session_id,
                "answer_text": answer,
            },
        ) as response:
            if response.status_code != 200:
                await response.aread()
                print(f"  {FAIL} HTTP {response.status_code}: {response.text[:500]}")
                return False
            stats = await parse_sse_stream(response)

    print(f"  SSE: {stats.summary()}")

    ok = True

    if stats.errors:
        print(f"  {FAIL} SSE errors: {stats.errors}")
        ok = False

    if stats.token_count == 0:
        print(f"  {WARN} No token events for answer evaluation")
    else:
        print(f"  {PASS} Received {stats.token_count} token events ({stats.token_chars} chars)")

    if "answer_evaluated" in stats.result_stages:
        for evt_type, evt_data in stats.all_events:
            if evt_type == "result" and evt_data.get("stage") == "answer_evaluated":
                eval_data = evt_data.get("data", {})
                ctx.answer_result = eval_data

                score = eval_data.get("overall_score", "N/A")
                rec = eval_data.get("recommendation", "N/A")
                answered = eval_data.get("questions_answered", 0)
                total = eval_data.get("total_questions", 0)
                progress = eval_data.get("progress_percent", 0)
                complete = eval_data.get("interview_complete", False)
                next_q = eval_data.get("next_question")

                print(f"  Score: {score}/100")
                print(f"  Recommendation: {rec}")
                print(f"  Progress: {answered}/{total} ({progress:.0f}%)")
                print(f"  Interview complete: {complete}")
                if next_q:
                    print(f"  Next question [{next_q.get('stage', '?')}]: {next_q.get('question_text', '')[:80]}...")
                print(f"  {PASS} Answer evaluated")
                break
    else:
        print(f"  {FAIL} No 'answer_evaluated' result event")
        ok = False

    if "done" in stats.event_counts:
        print(f"  {PASS} Stream completed")

    if ok:
        print(f"  {PASS} Answer submission complete")
    return ok


async def test_get_session(ctx: TestContext) -> bool:
    """Step 7: Get session details via REST."""
    print("\n" + "=" * 70)
    print("STEP 7: Get Session Details (REST)")
    print("=" * 70)

    headers = {"Authorization": f"Bearer {ctx.token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{ctx.base_url}/api/v1/sessions/{ctx.session_id}",
            headers=headers,
        )

    if resp.status_code != 200:
        print(f"  {FAIL} HTTP {resp.status_code}: {resp.text[:500]}")
        return False

    data = resp.json()
    status_val = data.get("status")
    answers = data.get("answers", [])
    total_q = data.get("total_questions", 0)
    current_q = data.get("current_question")

    print(f"  Status: {status_val}")
    print(f"  Answers submitted: {len(answers)}")
    print(f"  Total questions: {total_q}")

    if answers:
        last = answers[-1]
        strengths = last.get("strengths", [])
        improvements = last.get("improvements", [])
        print(f"  Last answer strengths: {len(strengths)}")
        if strengths:
            for s in strengths[:3]:
                print(f"    + {s}")
        print(f"  Last answer improvements: {len(improvements)}")
        if improvements:
            for i in improvements[:3]:
                print(f"    - {i}")
        print(f"  {PASS} Answer details with strengths/improvements retrieved")
    else:
        print(f"  {WARN} No answers in session data yet")

    if current_q:
        print(f"  Current question: [{current_q.get('stage', '?')}] {current_q.get('question_text', '')[:80]}...")

    print(f"  {PASS} Session details retrieved")
    return True


async def test_end_interview(ctx: TestContext) -> bool:
    """Step 8: End the interview via REST."""
    print("\n" + "=" * 70)
    print("STEP 8: End Interview (REST)")
    print("=" * 70)

    headers = {"Authorization": f"Bearer {ctx.token}"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{ctx.base_url}/api/v1/sessions/{ctx.session_id}/end",
            headers=headers,
            json={"reason": "E2E test complete"},
        )

    if resp.status_code != 200:
        print(f"  {FAIL} HTTP {resp.status_code}: {resp.text[:500]}")
        return False

    data = resp.json()
    print(f"  Response keys: {list(data.keys())}")
    overall = data.get("overall_score") or data.get("scores", {}).get("overall")
    rec = data.get("recommendation") or data.get("hiring_recommendation")
    print(f"  Overall score: {overall}")
    print(f"  Recommendation: {rec}")

    print(f"  {PASS} Interview ended")
    return True


async def test_get_report(ctx: TestContext) -> bool:
    """Step 9: Get interview report via REST."""
    print("\n" + "=" * 70)
    print("STEP 9: Get Report (REST)")
    print("=" * 70)

    headers = {"Authorization": f"Bearer {ctx.token}"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{ctx.base_url}/api/v1/reports/{ctx.session_id}",
            headers=headers,
        )

    if resp.status_code != 200:
        print(f"  {FAIL} HTTP {resp.status_code}: {resp.text[:500]}")
        return False

    data = resp.json()
    ctx.report = data
    print(f"  Report keys: {list(data.keys())}")
    print(f"  Overall score: {data.get('overall_score')}")
    print(f"  Recommendation: {data.get('recommendation') or data.get('hiring_recommendation')}")

    strengths = data.get("strengths", [])
    concerns = data.get("concerns", data.get("areas_for_improvement", []))
    if strengths:
        print(f"  Strengths ({len(strengths)}):")
        for s in strengths[:3]:
            print(f"    + {s}")
    if concerns:
        print(f"  Concerns ({len(concerns)}):")
        for c in concerns[:3]:
            print(f"    - {c}")

    print(f"  {PASS} Report retrieved")
    return True


async def test_cleanup(ctx: TestContext) -> bool:
    """Step 10: Clean up test data."""
    print("\n" + "=" * 70)
    print("STEP 10: Cleanup")
    print("=" * 70)

    headers = {"Authorization": f"Bearer {ctx.token}"}
    all_ok = True

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Delete session
        if ctx.session_id:
            resp = await client.delete(
                f"{ctx.base_url}/api/v1/sessions/{ctx.session_id}",
                headers=headers,
            )
            if resp.status_code == 200:
                print(f"  {PASS} Deleted session {ctx.session_id}")
            else:
                print(f"  {WARN} Failed to delete session: HTTP {resp.status_code}")

        # Delete resume
        if ctx.resume_id:
            resp = await client.delete(
                f"{ctx.base_url}/api/v1/documents/resumes/{ctx.resume_id}",
                headers=headers,
            )
            if resp.status_code == 200:
                print(f"  {PASS} Deleted resume {ctx.resume_id}")
            else:
                print(f"  {WARN} Failed to delete resume: HTTP {resp.status_code}")

        # Note: no delete endpoint for JDs in the current API, so we skip it
        if ctx.jd_id:
            print(f"  {INFO} JD {ctx.jd_id} left in DB (no delete endpoint)")

    print(f"  {PASS} Cleanup complete")
    return all_ok


# ============================================================
# Main
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="E2E streaming test against backend")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Backend URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--jwt-secret",
        default=DEFAULT_JWT_SECRET,
        help="JWT signing secret",
    )
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="Skip cleanup step (leave test data in DB)",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = generate_jwt(args.jwt_secret, role="admin", user_id="e2e-test-runner")

    ctx = TestContext(base_url=base_url, token=token)

    print("=" * 70)
    print("  E2E STREAMING TEST")
    print(f"  Backend: {base_url}")
    print(f"  Token: {token[:40]}...")
    print("=" * 70)

    steps = [
        ("Health Check", test_health),
        ("Upload Resume", test_upload_resume),
        ("Create JD", test_create_jd),
        ("Match Resume to JD", test_match),
        ("Start Interview", test_start_interview),
        ("Submit Answer", test_submit_answer),
        ("Get Session Details", test_get_session),
        ("End Interview", test_end_interview),
        ("Get Report", test_get_report),
    ]

    if not args.skip_cleanup:
        steps.append(("Cleanup", test_cleanup))

    results = {}
    start_time = time.time()

    for name, func in steps:
        try:
            passed = await func(ctx)
            results[name] = passed
            if not passed:
                print(f"\n  >>> Step '{name}' failed — stopping early")
                break
        except Exception as e:
            print(f"\n  {FAIL} Step '{name}' raised exception: {e}")
            traceback.print_exc()
            results[name] = False
            break

    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed
    skipped = len(steps) - total

    for name, ok in results.items():
        status_str = PASS if ok else FAIL
        print(f"  {status_str} {name}")

    for name, _ in steps:
        if name not in results:
            print(f"  [SKIP] {name}")

    print(f"\n  {passed}/{total} passed, {failed} failed, {skipped} skipped")
    print(f"  Total time: {elapsed:.1f}s")
    print("=" * 70)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
