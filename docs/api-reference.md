# API Reference

All endpoints are served from `http://localhost:8000`. Auth-required endpoints expect a `Bearer` JWT token in the `Authorization` header.

---

## Health (`src/api/health.py`)

### `GET /health`
**Auth:** None  
**Response:**
```json
{ "status": "healthy", "version": "1.0.0", "timestamp": "ISO8601" }
```

### `GET /health/detailed`
**Auth:** None  
**Response:**
```json
{
  "status": "healthy" | "degraded",
  "version": "1.0.0",
  "timestamp": "ISO8601",
  "components": {
    "mongodb": { "status": "healthy", "details": { "resumes_count": 5, ... } },
    "storage": { "status": "healthy", "backend": "local" | "s3" },
    "ollama":  { "status": "healthy", "models": ["qwen2.5:3b"] },
    "stt":     { "status": "healthy", "model_info": { ... } },
    "tts":     { "status": "healthy", "provider_info": { ... } }
  }
}
```
Returns `"degraded"` if any component fails. Each component is probed independently -- one failure doesn't block the others.

---

## Documents (`src/api/documents.py`, prefix: `/api/v1/documents`)

### `POST /api/v1/documents/resumes`
**Auth:** Required  
**Content-Type:** `multipart/form-data`  
**Body:** `file` (PDF or DOCX)  
**Response:** `ResumeUploadResponse` -- `{ id, filename, status, parsed_data: ParsedResume }`  
**Notes:** Uploads file to storage, extracts text (pdfplumber/python-docx), parses with LLM, saves to MongoDB.

### `GET /api/v1/documents/resumes/{resume_id}`
**Auth:** Required  
**Response:** Resume document from MongoDB.

### `GET /api/v1/documents/resumes`
**Auth:** Required  
**Response:** List of all resume documents.

### `DELETE /api/v1/documents/resumes/{resume_id}`
**Auth:** Required  
**Response:** Deletion confirmation.

### `POST /api/v1/documents/job-descriptions`
**Auth:** Required  
**Content-Type:** `application/json`  
**Body:** `JobDescriptionCreateRequest` -- `{ title, company, description, required_skills, preferred_skills, ... }`  
**Response:** `JobDescriptionResponse`  
**Notes:** Creates a JD from structured text input. Parses with LLM.

### `POST /api/v1/documents/job-descriptions/upload`
**Auth:** Required  
**Content-Type:** `multipart/form-data`  
**Body:** `file` (PDF or DOCX)  
**Response:** `JobDescriptionUploadResponse`  
**Notes:** Same as resume upload flow but for JD files.

### `GET /api/v1/documents/job-descriptions/{jd_id}`
**Auth:** Required  
**Response:** JD document from MongoDB.

### `GET /api/v1/documents/job-descriptions`
**Auth:** Required  
**Response:** List of all JD documents.

### `POST /api/v1/documents/match`
**Auth:** Required  
**Body:** `{ resume_id, jd_id }`  
**Response:** `MatchResult` (placeholder)  
**Notes:** **Currently returns placeholder data.** The `SemanticMatcher` exists but is not wired into this endpoint yet. See `known-issues.md`.

---

## Sessions (`src/api/sessions.py`, self-prefixed to `/api/v1/sessions`)

### `POST /api/v1/sessions/start`
**Auth:** Required  
**Body:** `StartInterviewRequest` -- `{ resume_id, jd_id, config?: InterviewConfig }`  
**Response:** `StartInterviewResponse` -- `{ session_id, status, current_question, total_questions }`  
**Notes:** Creates an `InterviewSession`, generates all questions upfront (hybrid bank+LLM). **Currently uses mock resume/JD data** instead of fetching from MongoDB -- see `known-issues.md`.

### `POST /api/v1/sessions/{session_id}/answer`
**Auth:** Required  
**Body:** `SubmitAnswerRequest` -- `{ question_id, answer_text }`  
**Response:** `SubmitAnswerResponse` -- `{ score, feedback, next_question?, session_complete }`  
**Notes:** Evaluates via LLM-as-judge. Automatically advances stage when all questions in current stage are answered.

### `GET /api/v1/sessions/{session_id}/progress`
**Auth:** Required  
**Response:** `InterviewProgressResponse` -- `{ status, current_stage, stage_progress, questions_answered, total_questions }`

### `GET /api/v1/sessions/{session_id}`
**Auth:** Required  
**Response:** Full `InterviewSession` object.

### `POST /api/v1/sessions/{session_id}/end`
**Auth:** Required  
**Body:** `EndInterviewRequest` (optional fields)  
**Response:** Report data or completion confirmation.

### `GET /api/v1/sessions/{session_id}/report`
**Auth:** Required  
**Response:** Generated interview report (JSON).

### `POST /api/v1/sessions/{session_id}/pause`
**Auth:** Required  
**Response:** Confirmation with updated session status.

### `POST /api/v1/sessions/{session_id}/resume`
**Auth:** Required  
**Response:** Resumed session with current question.

### `GET /api/v1/sessions/`
**Auth:** Required  
**Response:** List of all sessions.

### `DELETE /api/v1/sessions/{session_id}`
**Auth:** Required  
**Response:** Deletion confirmation. Removes from both in-memory dict and MongoDB.

---

## Interviews (`src/api/interviews.py`, prefix: `/api/v1/interviews`)

**Note:** This is a separate scheduling/CRUD system, partially implemented. It overlaps conceptually with sessions but operates on its own MongoDB `interviews` collection.

### `POST /api/v1/interviews/`
**Auth:** Required  
**Body:** Interview creation payload (candidate, JD, schedule).  
**Response:** Created interview document.

### `GET /api/v1/interviews/{interview_id}`
**Auth:** Required  
**Response:** Interview document.

### `GET /api/v1/interviews/`
**Auth:** Required  
**Response:** List of interviews.

### `POST /api/v1/interviews/{interview_id}/start`
**Auth:** Required  
**Response:** Started interview status.

### `POST /api/v1/interviews/{interview_id}/end`
**Auth:** Required  
**Response:** Ended interview status.

### `GET /api/v1/interviews/{interview_id}/report`
**Auth:** Required  
**Response:** Interview report.

---

## Questions (`src/api/questions.py`, prefix: `/api/v1/questions`)

### `POST /api/v1/questions/questions/generate`
**Auth:** Required  
**Body:** `{ resume_data, jd_data, stage, count, difficulty? }`  
**Response:** List of generated questions.  
**Notes:** Standalone endpoint for question generation outside of a session. Useful for testing.

### `POST /api/v1/questions/answers/evaluate`
**Auth:** Required  
**Body:** `{ question, answer, expected_topics? }`  
**Response:** `{ score, feedback, details }`

### `POST /api/v1/questions/answers/evaluate-behavioral`
**Auth:** Required  
**Body:** `{ question, answer }`  
**Response:** Behavioral (STAR) evaluation result.

### `POST /api/v1/questions/questions/follow-up`
**Auth:** Required  
**Body:** `{ original_question, answer, evaluation }`  
**Response:** Follow-up question.

### `GET /api/v1/questions/questions/stages`
**Auth:** Required  
**Response:** List of available interview stages.

### `GET /api/v1/questions/questions/difficulties`
**Auth:** Required  
**Response:** List of available difficulty levels.

---

## Voice (`src/api/voice.py`, self-prefixed to `/api/v1/voice`)

### `POST /api/v1/voice/transcribe`
**Auth:** Required  
**Content-Type:** `multipart/form-data`  
**Body:** `file` (audio file)  
**Response:** `{ text, language, confidence, duration }`

### `POST /api/v1/voice/transcribe/interview`
**Auth:** Required  
**Content-Type:** `multipart/form-data`  
**Body:** `file` (audio), `session_id` (form field)  
**Response:** Transcript with interview-context prompting (technical term bias).

### `POST /api/v1/voice/detect-language`
**Auth:** Required  
**Content-Type:** `multipart/form-data`  
**Body:** `file` (audio)  
**Response:** `{ language, confidence }`

### `GET /api/v1/voice/stt/info`
**Auth:** Required  
**Response:** STT provider info (model name, compute type, device).

### `GET /api/v1/voice/stt/models`
**Auth:** Required  
**Response:** Available Whisper model sizes.

### `POST /api/v1/voice/synthesize`
**Auth:** Required  
**Body:** `{ text, voice?, rate?, volume? }`  
**Response:** Audio bytes (WAV).

### `POST /api/v1/voice/synthesize/question`
**Auth:** Required  
**Body:** `{ text }`  
**Response:** Audio bytes with slower rate optimized for question readout.

### `GET /api/v1/voice/tts/voices`
**Auth:** Required  
**Response:** List of available system TTS voices.

### `GET /api/v1/voice/tts/info`
**Auth:** Required  
**Response:** TTS provider info (engine, current voice, rate, volume).

### `POST /api/v1/voice/tts/configure`
**Auth:** Required  
**Body:** `{ voice?, rate?, volume? }`  
**Response:** Updated TTS configuration.

### `GET /api/v1/voice/health`
**Auth:** Required  
**Response:** Voice subsystem health.

---

## Reports (`src/api/reports.py`, self-prefixed to `/api/v1/reports`)

### `GET /api/v1/reports/{session_id}`
**Auth:** Required  
**Response:** `FullInterviewReport` (JSON).

### `GET /api/v1/reports/{session_id}/pdf`
**Auth:** Required  
**Response:** PDF binary download (`Content-Disposition: attachment`).

### `GET /api/v1/reports/{session_id}/pdf/preview`
**Auth:** Required  
**Response:** PDF binary inline (`Content-Disposition: inline`).

### `DELETE /api/v1/reports/{session_id}/pdf`
**Auth:** Required  
**Response:** Deletion confirmation.

### `GET /api/v1/reports/`
**Auth:** Required  
**Response:** List of stored reports.

---

## Auth Notes

**Public paths** (no JWT required): `/health`, `/api/health`, `/docs`, `/redoc`, `/openapi.json`. These are prefix-matched in `src/api/middleware.py`.

**JWT format:**
```json
{
  "sub": "user_id",
  "username": "admin",
  "role": "admin",
  "exp": 1234567890
}
```

**Frontend token generation** is client-side in `frontend/api_client.py:59-78` using PyJWT. The shared secret is `"your-super-secret-key-change-in-production"` (must match `JWT_SECRET_KEY` in backend `.env`).
