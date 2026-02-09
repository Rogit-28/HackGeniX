# Architecture

## System Diagram

```
 Gradio UI (:7860)                 FastAPI (:8000)
 frontend/app.py                   src/main.py
 ┌──────────────┐  HTTP/JSON  ┌───────────────────────────────────┐
 │  Login       │────────────▶│  Auth Middleware                   │
 │  Documents   │             │  src/api/middleware.py             │
 │  Interviews  │             │         │                         │
 │  Live Session│             │         ▼                         │
 │  Reports     │             │  ┌─────────────────────────────┐  │
 │  Admin       │             │  │        API Routers           │  │
 │              │             │  │  health  documents  sessions │  │
 │  api_client  │◀────────────│  │  interviews  questions       │  │
 │  (PyJWT)     │             │  │  voice  reports              │  │
 └──────────────┘             │  └────────────┬────────────────┘  │
                              │               │                   │
                              │  ┌────────────▼────────────────┐  │
                              │  │      Services Layer          │  │
                              │  │  InterviewOrchestrator       │  │
                              │  │  DocumentProcessor           │  │
                              │  │  QuestionGenerator           │  │
                              │  │  AnswerEvaluator             │  │
                              │  │  SemanticMatcher             │  │
                              │  │  QuestionBankService         │  │
                              │  │  HybridQuestionSelector      │  │
                              │  │  PDFReportGenerator          │  │
                              │  └──┬──────────┬───────────┬──┘  │
                              │     │          │           │      │
                              └─────┼──────────┼───────────┼──────┘
                                    │          │           │
                     ┌──────────────┘          │           └──────────────┐
                     ▼                         ▼                         ▼
              ┌─────────────┐         ┌──────────────┐         ┌──────────────┐
              │  MongoDB    │         │   Ollama     │         │  Storage     │
              │  Atlas      │         │  :11434      │         │  local or S3 │
              │  (Motor)    │         │ qwen2.5:3b   │         │  ./storage/  │
              └─────────────┘         └──────────────┘         └──────────────┘
                                             │
                                    ┌────────┴────────┐
                                    ▼                 ▼
                             ┌───────────┐     ┌───────────┐
                             │ STT       │     │ TTS       │
                             │ faster-   │     │ pyttsx3   │
                             │ whisper   │     │ (SAPI5)   │
                             └───────────┘     └───────────┘
```

## Component Map

| Layer | File | Responsibility |
|-------|------|----------------|
| **Entry** | `src/main.py:82-88` | Mounts all routers, CORS, lifespan startup/shutdown |
| **Middleware** | `src/api/middleware.py` | JWT auth on non-public routes, injects `AuthenticatedUser` |
| **Auth** | `src/core/auth.py` | JWT encode/decode, `get_current_user`, `require_role()` |
| **Permissions** | `src/core/permissions.py` | Role-permission matrix, `require_permission()`, `require_session_access()` |
| **Config** | `src/core/config.py` | Pydantic-settings `Settings` from `.env`, `load_model_config()` from `config/models.yaml` |
| **Database** | `src/core/database.py` | Motor async client, collection accessors (`resumes`, `job_descriptions`, `interview_sessions`) |
| **Storage** | `src/core/storage.py` | S3/MinIO with local-filesystem fallback at `./storage/` |
| **Orchestrator** | `src/services/interview_orchestrator.py` | Central session controller -- start, submit answer, generate report, pause/resume |
| **Doc Processor** | `src/services/document_processor.py` | PDF (pdfplumber) + DOCX (python-docx) text extraction, LLM-based field parsing |
| **Question Gen** | `src/services/question_generator.py` | Pure-LLM and hybrid question generation |
| **Answer Eval** | `src/services/answer_evaluator.py` | LLM-as-judge scoring, hallucination check, report aggregation |
| **Semantic Match** | `src/services/semantic_matcher.py` | sentence-transformers (BAAI/bge-large-en-v1.5) resume-JD matching |
| **Question Bank** | `src/services/question_bank.py` | Loads/indexes JSONL files from `questionBank/domains/` |
| **Hybrid Selector** | `src/services/hybrid_question_selector.py` | Picks bank questions + identifies uncovered skills for LLM gap-fill |
| **PDF Generator** | `src/services/pdf_generator.py` | ReportLab single-page scrollable PDF report |
| **Prompts** | `src/services/prompts.py` | All LLM prompt templates (resume parsing, question gen, evaluation, etc.) |
| **LLM Factory** | `src/providers/llm/factory.py` | Creates Ollama/vLLM/OpenAI-compatible providers from `models.yaml` |
| **STT** | `src/providers/stt/faster_whisper_provider.py` | CTranslate2 Whisper, auto CUDA/CPU fallback |
| **TTS** | `src/providers/tts/pyttsx3_provider.py` | System TTS via pyttsx3, runs in thread pool executor |
| **Frontend** | `frontend/app.py` | Gradio tabbed UI (Login, Documents, Interviews, Live Session, Reports, Admin) |
| **API Client** | `frontend/api_client.py` | HTTP client + client-side JWT |

## Router Mounting

All routers are mounted in `src/main.py:82-88`:

```python
app.include_router(health.router)                                    # /health, /health/detailed
app.include_router(documents.router, prefix="/api/v1/documents")     # /api/v1/documents/*
app.include_router(interviews.router, prefix="/api/v1/interviews")   # /api/v1/interviews/*
app.include_router(questions.router, prefix="/api/v1/questions")     # /api/v1/questions/*
app.include_router(voice.router)                    # self-prefixed to /api/v1/voice/*
app.include_router(sessions.router)                 # self-prefixed to /api/v1/sessions/*
app.include_router(reports.router)                  # self-prefixed to /api/v1/reports/*
```

## Pipeline Flows

### 1. Document Upload (Resume)

```
POST /api/v1/documents/resumes  (multipart file)
  -> documents.py: validate file type (PDF/DOCX)
  -> storage_client.upload_bytes()  (S3 or ./storage/resumes/)
  -> DocumentProcessor.process_resume()
       -> extract text: pdfplumber (PDF) or python-docx (DOCX)
       -> SHA256 cache check in .cache/parsed_documents/
       -> if miss: LLM parse via RESUME_EXTRACTION_PROMPT
       -> normalize field names (contact/contact_info/personal_info, etc.)
       -> return ParsedResume
  -> save to MongoDB resumes collection
  -> return ResumeUploadResponse
```

### 2. Interview Session Lifecycle

```
POST /api/v1/sessions/start  {resume_id, jd_id, config}
  -> InterviewOrchestrator.start_interview()
       -> HybridQuestionSelector.select_questions()
            -> QuestionBankService: load JSONL, filter by domain/stage/difficulty
            -> Score by skill overlap with JD+resume, enforce category diversity
            -> Return (selected_bank_questions, uncovered_skills)
       -> QuestionGenerator.generate_questions_hybrid()
            -> Enhance bank questions with LLM (batch or single)
            -> Generate gap-fill questions for uncovered skills
       -> Create InterviewSession (in-memory _sessions dict + MongoDB)
       -> Return first question

POST /api/v1/sessions/{id}/answer  {question_id, answer_text}
  -> InterviewOrchestrator.submit_answer()
       -> AnswerEvaluator.evaluate_answer() or evaluate_behavioral_answer()
            -> LLM-as-judge with ANSWER_EVALUATION_PROMPT
            -> _validate_evaluation() hallucination check
       -> Record AnswerRecord, advance to next question or next stage
       -> Return evaluation + next question (or session complete signal)

POST /api/v1/sessions/{id}/end
  -> InterviewOrchestrator.generate_report()
       -> AnswerEvaluator.generate_interview_report()
            -> Aggregate scores (tech 40%, behavioral 25%, comm 20%, problem-solving 15%)
            -> LLM summary generation
            -> Validate recommendation vs calculated score
       -> PDFReportGenerator.generate_report() -> save PDF to storage
       -> Return FullInterviewReport
```

### 3. Voice Pipeline

```
POST /api/v1/voice/transcribe  (audio file)
  -> FasterWhisperSTTProvider.transcribe()
  -> Return {text, language, confidence}

POST /api/v1/voice/synthesize  {text}
  -> Pyttsx3TTSProvider.synthesize()  (in thread pool)
  -> Return audio bytes

POST /api/v1/voice/transcribe/interview  {audio, session_id}
  -> transcribe_with_interview_context()  (adds technical term prompts)
  -> Return transcript
```

## Port / URL Conventions

| Service | Default URL | Config |
|---------|------------|--------|
| FastAPI backend | `http://localhost:8000` | `uvicorn src.main:app --port 8000` |
| Gradio frontend | `http://localhost:7860` | `python -m frontend.app` |
| Ollama | `http://localhost:11434` | `OLLAMA_API_URL` env var |
| MongoDB Atlas | connection string | `MONGODB_URI` env var |
| Swagger docs | `http://localhost:8000/docs` | Auto-generated |
| ReDoc | `http://localhost:8000/redoc` | Auto-generated |

## Auth System

- **Algorithm:** JWT HS256, 60-minute expiry
- **Secret:** `JWT_SECRET_KEY` env var (default: `"your-super-secret-key-change-in-production"`)
- **Frontend generates tokens client-side** using PyJWT (`frontend/api_client.py:59-78`)
- **Public paths** (no auth): `/health`, `/api/health`, `/docs`, `/redoc`, `/openapi.json`
- **Roles:** `admin` > `hiring_manager` > `interviewer` > `candidate`

| Role | Capabilities |
|------|-------------|
| `admin` | All permissions |
| `hiring_manager` | Full CRUD on documents, interviews, reports, questions |
| `interviewer` | View documents, conduct interviews, use voice |
| `candidate` | Participate in assigned session, use voice |

## Singleton Pattern

All services use global singletons via `get_*()` factory functions, lazily initialized on first call:

- `get_interview_orchestrator()` -- `src/services/interview_orchestrator.py`
- `get_question_generator()` -- `src/services/question_generator.py`
- `get_answer_evaluator()` -- `src/services/answer_evaluator.py`
- `get_document_processor()` -- `src/services/document_processor.py`
- `get_semantic_matcher()` -- `src/services/semantic_matcher.py`
- `get_question_bank_service()` -- `src/services/question_bank.py`
- `get_hybrid_question_selector()` -- `src/services/hybrid_question_selector.py`
- `get_llm_provider()` (async) / `get_llm_provider_sync()` -- `src/providers/llm/factory.py`
- `get_faster_whisper_provider_async()` -- `src/providers/stt/faster_whisper_provider.py`
- `get_tts_provider_async()` -- `src/providers/tts/pyttsx3_provider.py`

**Gotcha:** Singletons are module-level globals. Server restart is the only way to force re-initialization. Hot reloading (uvicorn `--reload`) can cause stale references or duplicate instances.

## Directory Layout

```
HackGeniX/
  src/
    main.py                    # FastAPI app, router mounting, lifespan
    core/
      config.py                # Settings (pydantic-settings), load_model_config()
      database.py              # Motor MongoDB client, collection accessors
      storage.py               # S3/local storage client
      auth.py                  # JWT encode/decode, get_current_user
      permissions.py           # Role-permission matrix, require_*() deps
    models/
      documents.py             # ParsedResume, ParsedJobDescription, MatchResult
      interview.py             # InterviewSession, InterviewConfig, enums, request/response
      report.py                # FullInterviewReport, ScoreBreakdown, HiringRecommendation
      question_bank.py         # BankQuestion, EnrichedQuestion, QuestionCategory, domains
      auth.py                  # AuthenticatedUser, UserRole, TokenResponse
    services/
      interview_orchestrator.py  # Central session controller (1070 lines)
      question_generator.py      # LLM + hybrid question generation (927 lines)
      answer_evaluator.py        # LLM-as-judge evaluation (657 lines)
      document_processor.py      # PDF/DOCX parsing (603 lines)
      semantic_matcher.py        # Embedding-based resume-JD match (423 lines)
      question_bank.py           # JSONL question bank loader (525 lines)
      hybrid_question_selector.py  # Bank + LLM question selection (388 lines)
      pdf_generator.py           # ReportLab PDF generation (724 lines)
      prompts.py                 # All LLM prompt templates (702 lines)
    api/
      health.py                # GET /health, GET /health/detailed
      documents.py             # Resume + JD upload, list, delete, match
      sessions.py              # Interview session CRUD + answer submission
      interviews.py            # Interview scheduling (partially implemented)
      questions.py             # Question generation + evaluation endpoints
      voice.py                 # STT + TTS endpoints
      reports.py               # Report retrieval + PDF download
      middleware.py            # Auth middleware
    providers/
      llm/
        factory.py             # LLMProviderFactory, reads models.yaml
        base.py                # BaseLLMProvider ABC
        ollama_provider.py     # Ollama /api/chat integration
        vllm_provider.py       # OpenAI-compatible vLLM provider
      stt/
        faster_whisper_provider.py  # CTranslate2 Whisper
      tts/
        pyttsx3_provider.py    # System TTS via pyttsx3
      report_storage/
        base.py                # Abstract report storage
        local_provider.py      # Filesystem report storage
        s3_provider.py         # S3 report storage
  frontend/
    app.py                     # Gradio tabbed UI (984 lines)
    api_client.py              # HTTP client + client-side JWT
  config/
    models.yaml                # LLM/STT/TTS provider configuration
  questionBank/
    domains/                   # JSONL files per technical domain
  storage/                     # Local file storage fallback
  .cache/
    parsed_documents/          # SHA256-keyed document parse cache
  requirements.txt
  .env                         # Environment variables (not committed)
```
