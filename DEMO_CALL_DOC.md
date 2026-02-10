# HackGeniX - Demo Call

## 1. TECH STACK (One-liner answers)

| Layer | Technology | Why |
|---|---|---|
| **Backend** | FastAPI (Python 3.11) | Async, fast, auto-docs at `/docs` |
| **Frontend** | Gradio 4.0 (Python) | Rapid prototyping, tabbed UI at `:7860` |
| **Database** | MongoDB Atlas (Motor async driver) | Schema-flexible for evolving interview data |
| **LLM** | Ollama (local) + qwen2.5:3b | Zero API cost, data privacy, swappable |
| **Embeddings** | sentence-transformers / BAAI/bge-large-en-v1.5 | 1024-dim, CUDA-accelerated, local |
| **STT** | faster-whisper (CTranslate2) / large-v3 | Optimized Whisper, local, VAD-enabled |
| **TTS** | pyttsx3 (system TTS) | Zero-dependency, works offline |
| **File Storage** | S3/MinIO + local filesystem fallback | Production-ready + works without S3 |
| **Auth** | JWT (HS256) + RBAC (4 roles) | Stateless, role-based permissions |
| **PDF Reports** | ReportLab | Server-side PDF generation |
| **Config** | YAML (`config/models.yaml`) + `.env` | All models/providers swappable without code changes |

---

## 2. CORE ARCHITECTURE

```
Gradio UI (:7860)
    |
    v  (HTTP + JWT)
FastAPI (:8000)
    |
    +---> API Routers (7): health, documents, sessions, interviews, questions, voice, reports
    |
    +---> Services Layer
    |       |-- InterviewOrchestrator  (central controller, 1075 LOC)
    |       |-- QuestionGenerator      (LLM + hybrid question gen)
    |       |-- AnswerEvaluator        (LLM-as-Judge scoring)
    |       |-- SemanticMatcher        (embeddings + LLM sidecar)
    |       |-- DocumentProcessor      (PDF/DOCX parse via LLM)
    |       |-- HybridQuestionSelector (bank + gap-fill)
    |       |-- QuestionBank           (JSONL loader, 1500 curated Qs)
    |       +-- PDFGenerator           (ReportLab reports)
    |
    +---> Providers (pluggable via factory pattern)
    |       |-- LLM:    Ollama | vLLM (OpenAI-compatible)
    |       |-- STT:    faster-whisper | whisper
    |       |-- TTS:    pyttsx3
    |       +-- Storage: S3/MinIO | local filesystem
    |
    +---> MongoDB Atlas
            |-- resumes
            |-- job_descriptions
            |-- interviews
            |-- interview_sessions
            |-- candidates
            +-- reports
```

---

## 3. HOW QUESTIONS ARE MADE

### Two modes: Pure LLM vs Hybrid (default)

**Hybrid flow (recommended):**
1. Resume + JD uploaded --> parsed via LLM into structured JSON
2. `HybridQuestionSelector` auto-detects domains from JD (10 domains: backend, system_design, aiml, devops, security, web_dev, mobile, ml_ops, data_eng, software_eng)
3. Pulls curated questions from JSONL bank (1500 questions, 150/domain)
4. LLM optionally **rephrases** bank questions to add candidate-specific context
5. Identifies skill gaps not covered by bank --> LLM generates **gap-filling** questions
6. Final mix: configurable ratio (default ~60% bank, 40% LLM-generated)

**Interview stages (questions generated upfront per stage):**
- Screening --> Technical --> Behavioral --> System Design --> Wrap-up

**Adaptive difficulty:** After each answer, performance is tracked. If candidate scores high, difficulty ramps up (and vice versa).

---

## 4. WHERE WHICH MODEL IS USED

| Task | Model | Provider | File |
|---|---|---|---|
| Resume/JD parsing | qwen2.5:3b | Ollama | `services/document_processor.py` |
| Question generation | qwen2.5:3b | Ollama | `services/question_generator.py` |
| Question enhancement/rephrasing | qwen2.5:3b | Ollama | `services/question_generator.py` |
| Answer evaluation (LLM-as-Judge) | qwen2.5:3b | Ollama | `services/answer_evaluator.py` |
| Behavioral STAR evaluation | qwen2.5:3b | Ollama | `services/answer_evaluator.py` |
| Hallucination check on eval | qwen2.5:3b | Ollama | `services/answer_evaluator.py` |
| Interview summary/report | qwen2.5:3b | Ollama | `services/answer_evaluator.py` |
| Difficulty adjustment | qwen2.5:3b | Ollama | `services/question_generator.py` |
| Domain detection from JD | qwen2.5:3b | Ollama | `services/question_generator.py` |
| Resume-JD semantic matching | BAAI/bge-large-en-v1.5 | sentence-transformers | `services/semantic_matcher.py` |
| LLM qualitative fit sidecar | qwen2.5:3b | Ollama | `services/semantic_matcher.py` |
| Speech-to-Text | whisper large-v3 | faster-whisper (CTranslate2) | `providers/stt/faster_whisper_provider.py` |
| Text-to-Speech | system voices | pyttsx3 | `providers/tts/pyttsx3_provider.py` |

> All models run **locally**. Zero cloud API calls. The `openai` pip package is only used for OpenAI-compatible protocol with vLLM, never hits OpenAI servers.

---

## 5. FALLBACK LOGIC

| Component | Primary | Fallback | Trigger |
|---|---|---|---|
| **LLM Provider** | Configured provider (Ollama/vLLM) | Ollama + qwen2.5:3b | Health check failure on primary |
| **Question Generation** | LLM-generated questions | Hardcoded fallback Qs per stage | LLM generation fails |
| **Answer Evaluation** | LLM-as-Judge scoring | Default score = 50/100 | Any LLM/parsing error |
| **Document Parsing** | LLM structured extraction | Minimal `ParsedResume(raw_text=...)` | LLM failure |
| **Semantic Matching** | Hybrid (embeddings + LLM sidecar) | Core-only (embeddings, no LLM weight) | LLM sidecar failure |
| **STT (GPU)** | CUDA + float16/int8 | CPU + int8 auto-fallback | GPU not available/fails |
| **File Storage** | S3/MinIO | Local filesystem (`storage/`) | S3 not configured |
| **JSON Parsing** | Direct `json.loads()` | Strip markdown blocks, find JSON bounds | Malformed LLM output |

---

## 6. DB SCHEMAS (MongoDB Collections)

### `resumes`
```
{
  _id, candidate_id, filename, storage_key, content_type, file_size,
  parsed_data: {
    contact: { name, email, phone, linkedin, github, location },
    summary, skills[], experience[]: { company, title, dates, highlights[], skills[] },
    education[]: { institution, degree, field, gpa },
    projects[]: { name, description, tech_stack[], url },
    certifications[], soft_skills[]
  },
  embedding: [float x 1024],
  status: "uploaded|parsed|failed",
  created_at, updated_at
}
```

### `job_descriptions`
```
{
  _id, title, company, filename, storage_key,
  parsed_data: {
    title, company, location, employment_type, experience_level,
    salary_range: { min, max, currency },
    required_skills[], preferred_skills[],
    responsibilities[], qualifications[]
  },
  raw_text, embedding: [float x 1024],
  status, created_at, updated_at
}
```

### `interview_sessions`
```
{
  id, resume_id, jd_id,
  config: { mode: "text|voice|hybrid", questions_per_stage, adaptive_difficulty,
            bank_question_ratio, domains[], enable_rephrasing, enable_personalization },
  status: "created|in_progress|paused|completed|cancelled|failed",
  current_stage: "screening|technical|behavioral|system_design|wrap_up",
  questions[]: { id, text, stage, difficulty, category, expected_answer_points, source },
  answers[]: { question_id, question_text, stage, answer_text,
               scores: { technical_accuracy, completeness, clarity, depth, overall },
               strengths[], improvements[], duration_seconds },
  stage_progress: { stage: { total, answered, avg_score, time_spent } },
  current_difficulty, difficulty_history[],
  started_at, completed_at, total_duration
}
```

### `reports`
```
{
  interview_id, overall_score, technical_score, behavioral_score,
  communication_score, problem_solving_score,
  recommendation: "strong_hire|hire|no_hire|strong_no_hire",
  confidence, reasoning, strengths[], weaknesses[], summary,
  risk_factors[], next_steps[]
}
```

### `interviews` (scheduling layer)
```
{
  _id, candidate_id, job_description_id, interview_type: "technical|behavioral|mixed",
  status: "scheduled|in_progress|completed|cancelled",
  scheduled_at, started_at, ended_at, duration_minutes
}
```

---

## 7. AUTH & RBAC

- **JWT (HS256)**, 60-min expiry, stateless
- **4 Roles:** admin, hiring_manager, interviewer, candidate
- **20+ permissions** mapped to roles (CRUD on interviews, sessions, candidates, documents, questions, reports, voice, analysis)
- Client-side JWT generation (Gradio frontend creates tokens locally)

---

## 8. API ENDPOINTS (35+ across 7 routers)

| Router | Key Endpoints |
|---|---|
| **Health** | `GET /health`, `GET /health/detailed` |
| **Documents** | `POST /documents/resumes/upload`, `POST /documents/jd/upload`, `POST /documents/match/{resume_id}/{jd_id}` |
| **Sessions** | `POST /sessions/start`, `POST /sessions/{id}/answer`, `POST /sessions/{id}/end`, `GET /sessions/{id}/progress` |
| **Interviews** | `POST /interviews`, `GET /interviews`, `GET /interviews/{id}`, `PATCH /interviews/{id}/status` |
| **Questions** | `POST /questions/generate`, `POST /questions/evaluate`, `POST /questions/evaluate-behavioral`, `POST /questions/follow-up` |
| **Voice** | `POST /voice/transcribe`, `POST /voice/synthesize`, `GET /voice/voices` |
| **Reports** | `GET /reports/{session_id}`, `GET /reports/{session_id}/pdf` |

---

## 9. KEY NUMBERS

| Metric | Value |
|---|---|
| Backend Python LOC | ~14,500 |
| Frontend LOC | ~1,470 |
| Curated question bank | 1,500 questions across 10 domains |
| Interview stages | 5 (screening, technical, behavioral, system_design, wrap_up) |
| Question categories | 16 (explain, design, compare, troubleshoot, performance, etc.) |
| LLM prompt templates | 16 distinct prompts |
| MongoDB collections | 6 |
| API endpoints | 35+ |
| Test/script files | 23 |

---

## 10. COMMON DEMO QUESTIONS & ANSWERS

**Q: Is any data sent to external APIs?**
A: No. 100% local inference. Ollama runs on localhost. Embeddings are local sentence-transformers. STT is local Whisper. No data leaves the server.

**Q: Can we swap the LLM model?**
A: Yes. Change one line in `config/models.yaml` or set `PROVIDER_LLM_MODEL` env var. Supports any Ollama model or vLLM-served model. No code changes needed.

**Q: How is evaluation fairness ensured?**
A: Three safeguards: (1) LLM-as-Judge with structured rubric (0-100 per dimension), (2) Hallucination check validates evaluation is grounded in actual answer, (3) Recommendation override logic prevents LLM from hallucinating hire/no-hire decisions -- actual scores determine final recommendation.

**Q: What happens if the LLM is down?**
A: Factory pattern with health checks. Falls back to hardcoded questions, default scores (50/100), and minimal document parsing. System degrades gracefully, never crashes.

**Q: How does adaptive difficulty work?**
A: After each answer, performance trend is tracked. If avg score > threshold, next questions are harder. If below, easier. LLM generates difficulty-appropriate questions using the adjustment prompt.

**Q: Why MongoDB over SQL?**
A: Interview sessions have deeply nested, variable-shape data (questions, answers, scores, stage progress). Document model fits naturally. MongoDB Atlas provides managed hosting with zero-config scaling.

**Q: Can it handle voice interviews?**
A: Yes. Three modes: text, voice, hybrid. Voice uses faster-whisper (STT) + pyttsx3 (TTS). Audio is processed server-side. VAD (Voice Activity Detection) enabled for accurate transcription.

**Q: What about resume parsing accuracy?**
A: PDF/DOCX text extraction via pypdf2/pdfplumber/pymupdf, then LLM-structured extraction. Handles field name variations from small models. Results cached by file hash. Falls back to raw text on failure.

**Q: What's the question bank vs LLM split?**
A: Configurable ratio (default ~60% bank, 40% LLM). Bank provides consistency and quality baseline. LLM fills skill gaps and personalizes questions to the candidate's resume.

**Q: How are reports generated?**
A: Server-side PDF via ReportLab. Contains: executive summary, per-question evaluations with scores, strengths, concerns, hiring recommendation with confidence level, risk factors, and next steps.
