#!/usr/bin/env python
"""
End-to-end WebSocket voice interview test against the deployed (or local) backend.

Tests the full WebSocket interview lifecycle:
  1. Health check
  2. Upload resume (SSE)
  3. Create job description (SSE)
  4. Match resume to JD (SSE)
  5. Start interview session (SSE) — creates session with 3 questions
  6. Connect WebSocket — verify handshake
  7. Receive question + TTS audio + listening
  8. Send audio (pre-recorded WAV) + stop_recording — verify transcript + evaluation
  9. Receive next question — test text_answer (hybrid mode)
  10. Receive next question — test skip_question
  11. Verify interview_complete + WS closes
  12. Cleanup: delete session + resume

Usage:
    # Against Railway deployment:
    .venv\\Scripts\\python.exe scripts\\test_ws_interview.py

    # Against local backend:
    .venv\\Scripts\\python.exe scripts\\test_ws_interview.py --base-url http://localhost:8000

Environment variables:
    BACKEND_URL      - Backend base URL (default: http://localhost:8000)
    JWT_SECRET_KEY   - JWT signing secret (default: your-super-secret-key-change-in-production)
"""
import argparse
import asyncio
import io
import json
import os
import struct
import sys
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
import jwt
import websockets
from websockets.exceptions import ConnectionClosed


# ============================================================
# Configuration
# ============================================================

DEFAULT_BASE_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
DEFAULT_JWT_SECRET = os.environ.get(
    "JWT_SECRET_KEY",
    os.environ.get("JWT_SECRET", "your-super-secret-key-change-in-production"),
)

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
    session_id: Optional[str] = None
    first_question: Optional[Dict] = None
    ws_url: str = ""
    # Phase 7 augmentation tracking
    augmented_questions_seen: int = 0
    follow_up_questions_seen: int = 0
    max_follow_up_count: int = 0


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
    """Build a minimal .docx file in-memory from plain text."""
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

    if current_data_lines:
        data_str = "\n".join(current_data_lines)
        try:
            data_dict = json.loads(data_str)
        except json.JSONDecodeError:
            data_dict = {"raw": data_str}
        stats.record(current_event, data_dict)

    return stats


def generate_test_wav(duration_seconds: float = 2.0, sample_rate: int = 16000) -> bytes:
    """Generate a minimal WAV file with a sine wave tone.

    This creates a valid WAV file that Groq Whisper can accept for
    transcription. It contains a 440 Hz sine wave (A4 note) which
    won't produce meaningful speech but will validate the audio
    pipeline end-to-end.
    """
    import math

    num_samples = int(sample_rate * duration_seconds)
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * block_align

    # Generate 440 Hz sine wave samples
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        value = int(32767 * 0.5 * math.sin(2 * math.pi * 440 * t))
        samples.append(struct.pack('<h', value))

    audio_data = b''.join(samples)

    # Build WAV header
    wav = io.BytesIO()
    wav.write(b'RIFF')
    wav.write(struct.pack('<I', 36 + data_size))  # file size - 8
    wav.write(b'WAVE')
    wav.write(b'fmt ')
    wav.write(struct.pack('<I', 16))  # fmt chunk size
    wav.write(struct.pack('<H', 1))   # PCM format
    wav.write(struct.pack('<H', num_channels))
    wav.write(struct.pack('<I', sample_rate))
    wav.write(struct.pack('<I', byte_rate))
    wav.write(struct.pack('<H', block_align))
    wav.write(struct.pack('<H', bits_per_sample))
    wav.write(b'data')
    wav.write(struct.pack('<I', data_size))
    wav.write(audio_data)

    return wav.getvalue()


# ============================================================
# WebSocket message helpers
# ============================================================

async def ws_recv_json(ws_conn, timeout: float = 180.0) -> Optional[Dict]:
    """Receive a JSON text message from the WebSocket, skipping binary messages.

    Returns the parsed JSON dict, or None if the connection closes.
    Binary messages (TTS audio) are counted and skipped.
    """
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(f"No JSON message received within {timeout}s")
        try:
            msg = await asyncio.wait_for(ws_conn.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            raise TimeoutError(f"No JSON message received within {timeout}s")
        except ConnectionClosed:
            return None

        if isinstance(msg, str):
            return json.loads(msg)
        # Binary message (TTS audio chunk) — skip
        continue


async def ws_recv_until_type(
    ws_conn,
    target_type: str,
    timeout: float = 180.0,
    collect_binary: bool = False,
) -> Tuple[Optional[Dict], List[Dict], List[bytes]]:
    """Receive messages until a target JSON message type appears.

    Returns:
        (target_msg, intermediate_json_msgs, binary_chunks)
    """
    intermediates: List[Dict] = []
    binary_chunks: List[bytes] = []
    deadline = time.time() + timeout

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for message type '{target_type}' ({timeout}s)")
        try:
            msg = await asyncio.wait_for(ws_conn.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timed out waiting for message type '{target_type}' ({timeout}s)")
        except ConnectionClosed:
            return None, intermediates, binary_chunks

        if isinstance(msg, bytes):
            if collect_binary:
                binary_chunks.append(msg)
            continue

        data = json.loads(msg)
        if data.get("type") == target_type:
            return data, intermediates, binary_chunks
        intermediates.append(data)


async def ws_drain_messages(
    ws_conn,
    timeout: float = 2.0,
) -> Tuple[List[Dict], List[bytes]]:
    """Drain any pending messages (JSON and binary) within timeout."""
    json_msgs: List[Dict] = []
    binary_chunks: List[bytes] = []
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            msg = await asyncio.wait_for(ws_conn.recv(), timeout=remaining)
        except (asyncio.TimeoutError, ConnectionClosed):
            break

        if isinstance(msg, bytes):
            binary_chunks.append(msg)
        elif isinstance(msg, str):
            json_msgs.append(json.loads(msg))
    return json_msgs, binary_chunks


# ============================================================
# Test Steps (setup via SSE — reused from test_e2e_streaming)
# ============================================================

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"
INFO = "[INFO]"


async def setup_health(ctx: TestContext) -> bool:
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

    if not data.get("mongodb", False):
        print(f"  {FAIL} MongoDB is down — cannot proceed")
        return False

    print(f"  {PASS} Backend is reachable and healthy")
    return True


async def setup_upload_resume(ctx: TestContext) -> bool:
    """Step 2: Upload resume via SSE."""
    print("\n" + "=" * 70)
    print("STEP 2: Upload Resume (SSE)")
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

    if "upload_complete" in stats.result_stages:
        for evt_type, evt_data in stats.all_events:
            if evt_type == "result" and evt_data.get("stage") == "upload_complete":
                result_data = evt_data.get("data", {})
                ctx.resume_id = result_data.get("id")
                print(f"  Resume ID: {ctx.resume_id}")
                break

    if not ctx.resume_id:
        print(f"  {FAIL} No resume ID obtained")
        return False

    print(f"  {PASS} Resume uploaded")
    return True


async def setup_create_jd(ctx: TestContext) -> bool:
    """Step 3: Create JD via SSE."""
    print("\n" + "=" * 70)
    print("STEP 3: Create Job Description (SSE)")
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

    if "upload_complete" in stats.result_stages:
        for evt_type, evt_data in stats.all_events:
            if evt_type == "result" and evt_data.get("stage") == "upload_complete":
                result_data = evt_data.get("data", {})
                ctx.jd_id = result_data.get("id")
                print(f"  JD ID: {ctx.jd_id}")
                break

    if not ctx.jd_id:
        print(f"  {FAIL} No JD ID obtained")
        return False

    print(f"  {PASS} Job description created")
    return True


async def setup_match(ctx: TestContext) -> bool:
    """Step 4: Match resume to JD via SSE."""
    print("\n" + "=" * 70)
    print("STEP 4: Match Resume to JD (SSE)")
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

    if "match_complete" not in stats.result_stages:
        print(f"  {FAIL} No match_complete event")
        return False

    print(f"  {PASS} Matching complete")
    return True


async def setup_start_interview(ctx: TestContext) -> bool:
    """Step 5: Start interview session via SSE (3 questions)."""
    print("\n" + "=" * 70)
    print("STEP 5: Start Interview (SSE)")
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
                    "enable_question_augmentation": True,
                },
            },
        ) as response:
            if response.status_code != 200:
                await response.aread()
                print(f"  {FAIL} HTTP {response.status_code}: {response.text[:500]}")
                return False
            stats = await parse_sse_stream(response)

    print(f"  SSE: {stats.summary()}")

    if "interview_ready" in stats.result_stages:
        for evt_type, evt_data in stats.all_events:
            if evt_type == "result" and evt_data.get("stage") == "interview_ready":
                ready_data = evt_data.get("data", {})
                ctx.session_id = ready_data.get("session_id")
                ctx.first_question = ready_data.get("first_question")
                total_q = ready_data.get("total_questions", 0)
                print(f"  Session ID: {ctx.session_id}")
                print(f"  Total questions: {total_q}")
                if ctx.first_question:
                    print(f"  First question [{ctx.first_question.get('stage')}]: "
                          f"{ctx.first_question.get('question_text', '')[:80]}...")
                break

    if not ctx.session_id:
        print(f"  {FAIL} No session ID obtained")
        return False

    # Build WebSocket URL
    base = ctx.base_url
    if base.startswith("https://"):
        ws_base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        ws_base = "ws://" + base[len("http://"):]
    else:
        ws_base = "ws://" + base

    ctx.ws_url = f"{ws_base}/api/v1/interview/ws/{ctx.session_id}?token={ctx.token}"
    print(f"  WS URL: {ctx.ws_url[:80]}...")

    print(f"  {PASS} Interview started, ready for WebSocket")
    return True


# ============================================================
# WebSocket Test Steps
# ============================================================

async def test_ws_connect(ctx: TestContext) -> bool:
    """Step 6: Connect WebSocket and verify handshake."""
    print("\n" + "=" * 70)
    print("STEP 6: WebSocket Connect + Handshake")
    print("=" * 70)

    try:
        ws = await websockets.connect(
            ctx.ws_url,
            max_size=10 * 1024 * 1024,  # 10 MB max message
            open_timeout=30,
            close_timeout=10,
        )
    except Exception as exc:
        print(f"  {FAIL} WebSocket connection failed: {exc}")
        return False

    print(f"  {PASS} WebSocket connected")

    # Expect 'connected' handshake message
    try:
        msg = await ws_recv_json(ws, timeout=30.0)
    except TimeoutError:
        print(f"  {FAIL} Timeout waiting for 'connected' message")
        await ws.close()
        return False

    if not msg:
        print(f"  {FAIL} WebSocket closed before handshake")
        return False

    print(f"  Received: type={msg.get('type')}")
    print(f"    session_id: {msg.get('session_id')}")
    print(f"    candidate_name: {msg.get('candidate_name')}")
    print(f"    role_title: {msg.get('role_title')}")
    print(f"    current_stage: {msg.get('current_stage')}")
    print(f"    total_questions: {msg.get('total_questions')}")
    print(f"    questions_answered: {msg.get('questions_answered')}")

    if msg.get("type") != "connected":
        print(f"  {FAIL} Expected 'connected' message, got '{msg.get('type')}'")
        await ws.close()
        return False

    if msg.get("session_id") != ctx.session_id:
        print(f"  {FAIL} Session ID mismatch: {msg.get('session_id')} != {ctx.session_id}")
        await ws.close()
        return False

    print(f"  {PASS} Handshake verified")

    # --- Now receive question + TTS + listening ---
    print("\n  --- Receiving question + TTS audio + listening ---")

    # Expect: question -> tts_start -> [binary TTS chunks] -> tts_end -> listening
    question_msg, _, _ = await ws_recv_until_type(ws, "question", timeout=30.0)
    if not question_msg:
        print(f"  {FAIL} No 'question' message received")
        await ws.close()
        return False

    print(f"  Question: type={question_msg.get('type')}")
    print(f"    question_id: {question_msg.get('question_id')}")
    print(f"    question_text: {question_msg.get('question_text', '')[:80]}...")
    print(f"    stage: {question_msg.get('stage')}")
    print(f"    duration_seconds: {question_msg.get('duration_seconds')}")
    print(f"    question_number: {question_msg.get('question_number')}/{question_msg.get('total_questions')}")
    # Phase 7 fields
    print(f"    is_follow_up: {question_msg.get('is_follow_up', False)}")
    if question_msg.get('sub_question_label'):
        print(f"    sub_question_label: {question_msg.get('sub_question_label')}")
    if question_msg.get('follow_up_count', 0) > 0:
        print(f"    follow_up_count: {question_msg.get('follow_up_count')}")
        ctx.max_follow_up_count = max(ctx.max_follow_up_count, question_msg.get('follow_up_count', 0))
    if question_msg.get('is_follow_up'):
        ctx.follow_up_questions_seen += 1
    print(f"  {PASS} Question message received")

    # TTS start
    tts_start_msg, _, _ = await ws_recv_until_type(ws, "tts_start", timeout=30.0)
    if tts_start_msg:
        print(f"  TTS start: total_chunks={tts_start_msg.get('total_chunks')}")
        print(f"  {PASS} tts_start received")
    else:
        print(f"  {WARN} No tts_start received (TTS may have failed)")

    # TTS end (binary audio chunks arrive in between)
    tts_end_msg, tts_intermediates, tts_binary = await ws_recv_until_type(
        ws, "tts_end", timeout=120.0, collect_binary=True,
    )
    if tts_end_msg:
        total_audio_bytes = sum(len(b) for b in tts_binary)
        print(f"  TTS end: duration_seconds={tts_end_msg.get('duration_seconds'):.2f}")
        print(f"  TTS audio: {len(tts_binary)} chunks, {total_audio_bytes} bytes total")
        if tts_intermediates:
            for im in tts_intermediates:
                print(f"    Intermediate: type={im.get('type')}, msg={im.get('message', '')[:60]}")
        print(f"  {PASS} tts_end received with audio data")
    else:
        print(f"  {WARN} No tts_end received (TTS may have failed)")

    # Listening
    listening_msg, _, _ = await ws_recv_until_type(ws, "listening", timeout=30.0)
    if not listening_msg:
        print(f"  {FAIL} No 'listening' message received")
        await ws.close()
        return False

    print(f"  Listening: duration_seconds={listening_msg.get('duration_seconds')}")
    print(f"    auto_submit_on_expire: {listening_msg.get('auto_submit_on_expire')}")
    print(f"  {PASS} listening received — mic should open")

    # --- Step 7: Send audio + stop_recording ---
    print("\n" + "=" * 70)
    print("STEP 7: Send Audio + Stop Recording (Voice Mode)")
    print("=" * 70)

    # Send audio_meta
    await ws.send(json.dumps({
        "type": "audio_meta",
        "mime_type": "audio/wav",
    }))
    print(f"  Sent audio_meta (audio/wav)")

    # Generate and send test WAV
    wav_data = generate_test_wav(duration_seconds=2.0, sample_rate=16000)
    print(f"  Generated test WAV: {len(wav_data)} bytes (2s, 16kHz, mono)")

    # Send in chunks (simulating MediaRecorder chunks)
    chunk_size = 8192
    chunks_sent = 0
    for i in range(0, len(wav_data), chunk_size):
        chunk = wav_data[i:i + chunk_size]
        await ws.send(chunk)
        chunks_sent += 1

    print(f"  Sent {chunks_sent} audio chunks ({len(wav_data)} bytes total)")

    # Small delay to simulate recording time
    await asyncio.sleep(0.5)

    # Stop recording
    await ws.send(json.dumps({
        "type": "control",
        "action": "stop_recording",
    }))
    print(f"  Sent control: stop_recording")

    # Expect: transcript (or error if no speech) -> evaluating -> evaluation
    # Since we sent a sine wave, Whisper may return empty text or noise.
    # The handler will either:
    #   a) Send transcript + evaluation (if Whisper found some "text")
    #   b) Send error + re-open listening (if no speech detected)
    # We handle both cases.

    print(f"\n  --- Waiting for transcript/evaluation ---")

    # Collect messages until we get 'evaluation' or 'listening' (re-opened)
    got_transcript = False
    got_evaluation = False
    got_error = False
    got_listening_reopen = False
    evaluation_msg = None
    transcript_text = ""

    deadline = time.time() + 120.0
    while time.time() < deadline:
        remaining = deadline - time.time()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except (asyncio.TimeoutError, ConnectionClosed):
            break

        if isinstance(raw, bytes):
            continue  # skip binary

        data = json.loads(raw)
        msg_type = data.get("type")
        print(f"    Received: type={msg_type}")

        if msg_type == "transcript":
            got_transcript = True
            transcript_text = data.get("text", "")
            print(f"      text: {transcript_text[:100]}")
            print(f"      is_final: {data.get('is_final')}")
            print(f"      confidence: {data.get('confidence')}")

        elif msg_type == "evaluating":
            print(f"      message: {data.get('message')}")

        elif msg_type == "progress":
            print(f"      stage: {data.get('current_stage')}")

        elif msg_type == "evaluation":
            got_evaluation = True
            evaluation_msg = data
            print(f"      overall_score: {data.get('overall_score')}")
            print(f"      scores: {data.get('scores')}")
            print(f"      strengths: {data.get('strengths', [])[:2]}")
            print(f"      improvements: {data.get('improvements', [])[:2]}")
            print(f"      questions_answered: {data.get('questions_answered')}/{data.get('total_questions')}")
            print(f"      stage_changed: {data.get('stage_changed')}")
            print(f"      interview_complete: {data.get('interview_complete')}")
            # Phase 7 fields
            if data.get('follow_up_count', 0) > 0:
                print(f"      follow_up_count: {data.get('follow_up_count')}")
                ctx.max_follow_up_count = max(ctx.max_follow_up_count, data.get('follow_up_count', 0))
            break  # evaluation is the terminal event for this question

        elif msg_type == "error":
            got_error = True
            print(f"      error: {data.get('message')}")
            print(f"      recoverable: {data.get('recoverable')}")

        elif msg_type == "listening":
            got_listening_reopen = True
            print(f"      Mic re-opened (no speech detected in sine wave)")
            break

        elif msg_type == "stage_change":
            print(f"      from_stage: {data.get('from_stage')} -> to_stage: {data.get('to_stage')}")

        elif msg_type == "question":
            # Next question arrived (comes after evaluation)
            print(f"      Next question arrived (unexpected here, should come after eval)")

    if got_evaluation:
        print(f"  {PASS} Voice answer: transcript + evaluation received")
    elif got_listening_reopen:
        print(f"  {WARN} Sine wave produced no speech — mic re-opened (expected behavior)")
        print(f"  Falling back to text_answer for this question...")

        # Send text answer as fallback
        await ws.send(json.dumps({
            "type": "text_answer",
            "text": (
                "In my experience as a Senior Software Engineer at TechCorp, I have "
                "worked extensively with Python and FastAPI to build scalable microservices. "
                "I designed a real-time data pipeline processing 10 million events per day "
                "using Kafka and Flink."
            ),
        }))
        print(f"  Sent text_answer fallback")

        # Wait for transcript echo + evaluation
        deadline2 = time.time() + 120.0
        while time.time() < deadline2:
            remaining = deadline2 - time.time()
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except (asyncio.TimeoutError, ConnectionClosed):
                break
            if isinstance(raw, bytes):
                continue
            data = json.loads(raw)
            msg_type = data.get("type")
            print(f"    Received: type={msg_type}")

            if msg_type == "transcript":
                got_transcript = True
                print(f"      text: {data.get('text', '')[:80]}...")

            elif msg_type == "evaluating":
                print(f"      message: {data.get('message')}")

            elif msg_type == "progress":
                print(f"      stage: {data.get('current_stage')}")

            elif msg_type == "evaluation":
                got_evaluation = True
                evaluation_msg = data
                print(f"      overall_score: {data.get('overall_score')}")
                print(f"      questions_answered: {data.get('questions_answered')}/{data.get('total_questions')}")
                print(f"      interview_complete: {data.get('interview_complete')}")
                # Phase 7 fields
                if data.get('follow_up_count', 0) > 0:
                    print(f"      follow_up_count: {data.get('follow_up_count')}")
                    ctx.max_follow_up_count = max(ctx.max_follow_up_count, data.get('follow_up_count', 0))
                break

            elif msg_type == "stage_change":
                print(f"      from: {data.get('from_stage')} -> to: {data.get('to_stage')}")

        if got_evaluation:
            print(f"  {PASS} Text fallback: evaluation received")
        else:
            print(f"  {FAIL} No evaluation received after text fallback")
            await ws.close()
            return False
    else:
        print(f"  {FAIL} Neither evaluation nor listening re-open received")
        await ws.close()
        return False

    # Check if interview is complete already
    if evaluation_msg and evaluation_msg.get("interview_complete"):
        print(f"  {INFO} Interview complete after question 1 (unexpected for 3-question config)")
        await ws.close()
        return True

    # --- Step 8: Receive next question + test text_answer (hybrid mode) ---
    print("\n" + "=" * 70)
    print("STEP 8: Text Answer (Hybrid Mode) — Question 2")
    print("=" * 70)

    # If we already received evaluation, the handler sends the next question
    # immediately. We need to collect: question -> tts_start -> [binary] -> tts_end -> listening
    # Or we might already have the question from the evaluation flow.

    # Receive next question + TTS + listening
    q2_msg, q2_intermediates, _ = await ws_recv_until_type(ws, "question", timeout=60.0)
    if not q2_msg:
        # Maybe it was already sent as part of evaluation flow
        print(f"  {WARN} No question message for Q2 — checking intermediates")
        print(f"  {FAIL} Could not get question 2")
        await ws.close()
        return False

    print(f"  Question 2: {q2_msg.get('question_text', '')[:80]}...")
    print(f"    stage: {q2_msg.get('stage')}")
    print(f"    question_number: {q2_msg.get('question_number')}/{q2_msg.get('total_questions')}")
    # Phase 7 fields
    print(f"    is_follow_up: {q2_msg.get('is_follow_up', False)}")
    if q2_msg.get('sub_question_label'):
        print(f"    sub_question_label: {q2_msg.get('sub_question_label')}")
    if q2_msg.get('follow_up_count', 0) > 0:
        print(f"    follow_up_count: {q2_msg.get('follow_up_count')}")
        ctx.max_follow_up_count = max(ctx.max_follow_up_count, q2_msg.get('follow_up_count', 0))
    if q2_msg.get('is_follow_up'):
        ctx.follow_up_questions_seen += 1

    # Wait for TTS + listening
    listening_msg2, _, tts_binary2 = await ws_recv_until_type(
        ws, "listening", timeout=120.0, collect_binary=True,
    )
    if listening_msg2:
        tts_bytes2 = sum(len(b) for b in tts_binary2)
        print(f"  TTS audio: {len(tts_binary2)} chunks, {tts_bytes2} bytes")
        print(f"  Listening: duration_seconds={listening_msg2.get('duration_seconds')}")
        print(f"  {PASS} Question 2 delivered with TTS")
    else:
        print(f"  {WARN} No listening message for Q2 — proceeding anyway")

    # Send text answer (hybrid mode — no audio)
    text_answer = (
        "I have extensive experience leading teams in agile environments. "
        "At TechCorp, I mentored 4 junior engineers and established code review "
        "best practices across 3 teams. I believe in servant leadership and "
        "creating an environment where engineers feel safe to experiment and learn."
    )
    await ws.send(json.dumps({
        "type": "text_answer",
        "text": text_answer,
    }))
    print(f"  Sent text_answer: {text_answer[:60]}...")

    # Wait for evaluation
    eval2_msg, eval2_intermediates, _ = await ws_recv_until_type(
        ws, "evaluation", timeout=120.0,
    )
    if not eval2_msg:
        print(f"  {FAIL} No evaluation received for Q2 text answer")
        await ws.close()
        return False

    print(f"  Evaluation Q2:")
    print(f"    overall_score: {eval2_msg.get('overall_score')}")
    print(f"    questions_answered: {eval2_msg.get('questions_answered')}/{eval2_msg.get('total_questions')}")
    print(f"    stage_changed: {eval2_msg.get('stage_changed')}")
    print(f"    interview_complete: {eval2_msg.get('interview_complete')}")
    # Phase 7 fields
    if eval2_msg.get('follow_up_count', 0) > 0:
        print(f"    follow_up_count: {eval2_msg.get('follow_up_count')}")
        ctx.max_follow_up_count = max(ctx.max_follow_up_count, eval2_msg.get('follow_up_count', 0))
    for im in eval2_intermediates:
        if im.get("type") == "transcript":
            print(f"    transcript echo: {im.get('text', '')[:60]}...")
        elif im.get("type") == "stage_change":
            print(f"    stage_change: {im.get('from_stage')} -> {im.get('to_stage')}")
    print(f"  {PASS} Hybrid text answer evaluated")

    if eval2_msg.get("interview_complete"):
        print(f"  {INFO} Interview complete after Q2")
        # Expect interview_complete message
        complete_msg = await ws_recv_json(ws, timeout=30.0)
        if complete_msg and complete_msg.get("type") == "interview_complete":
            print(f"  {PASS} interview_complete message received")
        await ws.close()
        return True

    # --- Step 9: Skip question (Question 3) ---
    print("\n" + "=" * 70)
    print("STEP 9: Skip Question — Question 3")
    print("=" * 70)

    # Receive Q3
    q3_msg, _, _ = await ws_recv_until_type(ws, "question", timeout=60.0)
    if not q3_msg:
        print(f"  {FAIL} No question 3 received")
        await ws.close()
        return False

    print(f"  Question 3: {q3_msg.get('question_text', '')[:80]}...")
    print(f"    stage: {q3_msg.get('stage')}")
    print(f"    question_number: {q3_msg.get('question_number')}/{q3_msg.get('total_questions')}")
    # Phase 7 fields
    print(f"    is_follow_up: {q3_msg.get('is_follow_up', False)}")
    if q3_msg.get('sub_question_label'):
        print(f"    sub_question_label: {q3_msg.get('sub_question_label')}")
    if q3_msg.get('follow_up_count', 0) > 0:
        print(f"    follow_up_count: {q3_msg.get('follow_up_count')}")
        ctx.max_follow_up_count = max(ctx.max_follow_up_count, q3_msg.get('follow_up_count', 0))
    if q3_msg.get('is_follow_up'):
        ctx.follow_up_questions_seen += 1

    # Wait for listening
    listening_msg3, _, tts_binary3 = await ws_recv_until_type(
        ws, "listening", timeout=120.0, collect_binary=True,
    )
    if listening_msg3:
        tts_bytes3 = sum(len(b) for b in tts_binary3)
        print(f"  TTS audio: {len(tts_binary3)} chunks, {tts_bytes3} bytes")
        print(f"  Listening: duration_seconds={listening_msg3.get('duration_seconds')}")
        print(f"  {PASS} Question 3 delivered")

    # Skip the question
    await ws.send(json.dumps({
        "type": "control",
        "action": "skip_question",
    }))
    print(f"  Sent control: skip_question")

    # Expect: evaluating -> evaluation -> (interview_complete if last question)
    # Skip sends "(Question skipped by candidate)" to evaluator
    skip_deadline = time.time() + 120.0
    got_skip_eval = False
    got_complete = False

    while time.time() < skip_deadline:
        remaining = skip_deadline - time.time()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except (asyncio.TimeoutError, ConnectionClosed):
            break

        if isinstance(raw, bytes):
            continue

        data = json.loads(raw)
        msg_type = data.get("type")
        print(f"    Received: type={msg_type}")

        if msg_type == "evaluating":
            print(f"      message: {data.get('message')}")

        elif msg_type == "progress":
            print(f"      stage: {data.get('current_stage')}")

        elif msg_type == "evaluation":
            got_skip_eval = True
            print(f"      overall_score: {data.get('overall_score')}")
            print(f"      questions_answered: {data.get('questions_answered')}/{data.get('total_questions')}")
            print(f"      interview_complete: {data.get('interview_complete')}")
            # Phase 7 fields
            if data.get('follow_up_count', 0) > 0:
                print(f"      follow_up_count: {data.get('follow_up_count')}")
                ctx.max_follow_up_count = max(ctx.max_follow_up_count, data.get('follow_up_count', 0))

        elif msg_type == "stage_change":
            print(f"      stage_change: {data.get('from_stage')} -> {data.get('to_stage')}")

        elif msg_type == "interview_complete":
            got_complete = True
            print(f"      overall_score: {data.get('overall_score')}")
            print(f"      questions_answered: {data.get('questions_answered')}/{data.get('total_questions')}")
            print(f"      duration_minutes: {data.get('duration_minutes')}")
            print(f"      message: {data.get('message')}")
            break

        elif msg_type == "question":
            # Q4 (wrap-up) may arrive after skip — this is expected when
            # the session has more questions beyond the skipped one
            print(f"      Next question: {data.get('question_text', '')[:60]}...")
            print(f"      (wrap-up/extra question — will end interview)")
            break

    if got_skip_eval:
        print(f"  {PASS} Skip evaluated")
    else:
        print(f"  {FAIL} No evaluation for skipped question")

    if got_complete:
        print(f"  {PASS} interview_complete received — WS should close")
    else:
        # Interview may not be complete if there are more questions. Try end_interview.
        print(f"  {INFO} Interview not complete after skip — sending end_interview")

        await ws.send(json.dumps({
            "type": "control",
            "action": "end_interview",
        }))
        print(f"  Sent control: end_interview")

        end_msg, _, _ = await ws_recv_until_type(ws, "interview_complete", timeout=60.0)
        if end_msg:
            print(f"  {PASS} interview_complete received after end_interview")
            got_complete = True
        else:
            print(f"  {FAIL} No interview_complete after end_interview")

    # WebSocket should be closed by server
    try:
        await asyncio.wait_for(ws.wait_closed(), timeout=5.0)
        print(f"  {PASS} WebSocket closed by server (code={ws.close_code})")
    except asyncio.TimeoutError:
        print(f"  {WARN} WebSocket not closed by server — closing client-side")
        await ws.close()

    return got_complete


async def test_cleanup(ctx: TestContext) -> bool:
    """Step 10: Clean up test data."""
    print("\n" + "=" * 70)
    print("STEP 10: Cleanup")
    print("=" * 70)

    headers = {"Authorization": f"Bearer {ctx.token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        if ctx.session_id:
            resp = await client.delete(
                f"{ctx.base_url}/api/v1/sessions/{ctx.session_id}",
                headers=headers,
            )
            if resp.status_code == 200:
                print(f"  {PASS} Deleted session {ctx.session_id}")
            else:
                print(f"  {WARN} Failed to delete session: HTTP {resp.status_code}")

        if ctx.resume_id:
            resp = await client.delete(
                f"{ctx.base_url}/api/v1/documents/resumes/{ctx.resume_id}",
                headers=headers,
            )
            if resp.status_code == 200:
                print(f"  {PASS} Deleted resume {ctx.resume_id}")
            else:
                print(f"  {WARN} Failed to delete resume: HTTP {resp.status_code}")

        if ctx.jd_id:
            print(f"  {INFO} JD {ctx.jd_id} left in DB (no delete endpoint)")

    print(f"  {PASS} Cleanup complete")
    return True


# ============================================================
# Main
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="E2E WebSocket voice interview test")
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
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip SSE setup steps (requires --session-id)",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Existing session ID (use with --skip-setup)",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = generate_jwt(args.jwt_secret, role="admin", user_id="e2e-ws-test-runner")

    ctx = TestContext(base_url=base_url, token=token)

    print("=" * 70)
    print("  E2E WEBSOCKET VOICE INTERVIEW TEST")
    print(f"  Backend: {base_url}")
    print(f"  Token: {token[:40]}...")
    print("=" * 70)

    results = {}
    start_time = time.time()

    if args.skip_setup:
        if not args.session_id:
            print(f"  {FAIL} --skip-setup requires --session-id")
            sys.exit(1)
        ctx.session_id = args.session_id

        # Build WS URL
        if base_url.startswith("https://"):
            ws_base = "wss://" + base_url[len("https://"):]
        elif base_url.startswith("http://"):
            ws_base = "ws://" + base_url[len("http://"):]
        else:
            ws_base = "ws://" + base_url
        ctx.ws_url = f"{ws_base}/api/v1/interview/ws/{ctx.session_id}?token={ctx.token}"

        setup_steps = []
    else:
        setup_steps = [
            ("Health Check", setup_health),
            ("Upload Resume", setup_upload_resume),
            ("Create JD", setup_create_jd),
            ("Match Resume to JD", setup_match),
            ("Start Interview", setup_start_interview),
        ]

    ws_steps = [
        ("WebSocket Interview (connect + Q1 voice + Q2 text + Q3 skip)", test_ws_connect),
    ]

    cleanup_steps = []
    if not args.skip_cleanup:
        cleanup_steps.append(("Cleanup", test_cleanup))

    all_steps = setup_steps + ws_steps + cleanup_steps

    for name, func in all_steps:
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
    passed_count = sum(1 for v in results.values() if v)
    failed_count = total - passed_count
    skipped_count = len(all_steps) - total

    for name, ok in results.items():
        status_str = PASS if ok else FAIL
        print(f"  {status_str} {name}")

    for name, _ in all_steps:
        if name not in results:
            print(f"  [SKIP] {name}")

    print(f"\n  {passed_count}/{total} passed, {failed_count} failed, {skipped_count} skipped")
    print(f"  Total time: {elapsed:.1f}s")

    # Phase 7: Augmentation summary
    print("\n  --- Phase 7: Question Augmentation ---")
    print(f"  enable_question_augmentation: True (explicitly set in config)")
    print(f"  Follow-up questions seen: {ctx.follow_up_questions_seen}")
    print(f"  Max follow_up_count reported: {ctx.max_follow_up_count}")
    if ctx.follow_up_questions_seen > 0:
        print(f"  {PASS} Follow-up sub-questions were generated by augmentation pipeline")
    else:
        print(f"  {INFO} No follow-up sub-questions generated (expected with only 3 base questions —")
        print(f"         should_follow_up() returns False when questions_remaining < 3)")
    print(f"  {INFO} Question augmentation (text modification) happens server-side;")
    print(f"         check question_text in logs above to verify questions were contextually adapted")

    print("=" * 70)

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
