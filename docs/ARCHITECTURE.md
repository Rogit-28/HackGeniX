# Architecture

## System Diagram

```
 HuggingFace Spaces                    Railway (Cloud)
 HackGeniX-hf-space/app.py            src/main.py
 ┌──────────────────┐  HTTPS/JSON  ┌───────────────────────────────────┐
 │  Gradio UI        │─────────────▶│  Auth Middleware                   │
 │  Login            │              │  src/api/middleware.py             │
 │  Documents        │              │         │                         │
 │  Interviews       │              │         ▼                         │
 │  Live Session     │              │  ┌─────────────────────────────┐  │
 │  Reports          │              │  │        API Routers           │  │
 │  Admin            │              │  │  health  documents  sessions │  │
 │                   │◀─────────────│  │  interviews  questions       │  │
 │  api_client       │              │  │  voice  reports              │  │
 │  (PyJWT)          │              │  └────────────┬────────────────┘  │
 └──────────────────┘              │               │                   │
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
                       ┌──────────────────┘          │           └──────────────┐
                       ▼                             ▼                         ▼
                ┌─────────────┐         ┌──────────────────┐         ┌──────────────┐
                │  MongoDB    │         │   Groq Cloud     │         │  Storage     │
                │  Atlas      │         │   API            │         │  local or S3 │
                │  (Motor)    │         │                  │         │  ./storage/  │
                └─────────────┘         └──────────────────┘         └──────────────┘
                                               │
                                    ┌──────────┼──────────┐
                                    ▼          ▼          ▼
                             ┌───────────┐ ┌────────┐ ┌────────┐
                             │ LLM       │ │ STT    │ │ TTS    │
                             │ llama-3.1 │ │ Whisper│ │ Orpheus│
                             │ -8b-      │ │ large  │ │ (troy) │
                             │ instant   │ │ -v3    │ │        │
                             └───────────┘ └────────┘ └────────┘

 Embeddings run locally on Railway:
 sentence-transformers/all-MiniLM-L6-v2 (384-dim, CPU)
```

## Cloud Deployment

| Component | Platform | URL |
|-----------|----------|-----|
| **Backend (FastAPI)** | Railway | `https://hackgenix-production.up.railway.app` |
| **Frontend (Gradio)** | HuggingFace Spaces | `https://huggingface.co/spaces/rs2803/HackGeniX` |
| **LLM / STT / TTS** | Groq Cloud API | `https://api.groq.com/openai/v1` |
| **Database** | MongoDB Atlas | connection string via `MONGODB_URI` |

The backend and frontend are **separate git repos**. Backend pushes auto-deploy to Railway. Frontend pushes auto-deploy to the HF Space.

### Required Environment Variables (Railway)

| Variable | Purpose |
|----------|---------|
| `GROQ_API_KEY` | Groq Cloud API authentication |
| `MONGODB_URI` | MongoDB Atlas connection string |
| `JWT_SECRET_KEY` | JWT signing secret (must override default in production) |
| `PORT` | Set automatically by Railway |
| `APP_ENV` | Set to `"production"` to disable debug mode and docs |

### Deployment Files

| File | Purpose |
|------|---------|
| `Procfile` | `web: uvicorn src.main:app --host 0.0.0.0 --port $PORT` |
| `Aptfile` | Installs `tesseract-ocr` and `tesseract-ocr-eng` system packages for OCR fallback |
| `requirements.txt` | Python dependencies |

## Component Map

| Layer | File | Responsibility |
|-------|------|----------------|
| **Entry** | `src/main.py` | NVIDIA CUDA DLL registration, eager-load embedding model + TTS, mounts all routers, CORS, lifespan startup/shutdown |
| **Middleware** | `src/api/middleware.py` | JWT auth on non-public routes, injects `AuthenticatedUser` |
| **Auth** | `src/core/auth.py` | JWT encode/decode, `get_current_user`, `require_role()` |
| **Permissions** | `src/core/permissions.py` | Role-permission matrix, `require_permission()`, `require_session_access()` |
| **Config** | `src/core/config.py` | Pydantic-settings `Settings` from `.env`, `load_model_config()` from `config/models.yaml` |
| **Database** | `src/core/database.py` | Motor async client, collection accessors (`resumes`, `job_descriptions`, `interview_sessions`) |
| **Storage** | `src/core/storage.py` | S3/MinIO with local-filesystem fallback at `./storage/` |
| **Orchestrator** | `src/services/interview_orchestrator.py` | Central session controller -- start, submit answer, generate report, pause/resume; MongoDB write-through persistence via SessionRepository |
| **Doc Processor** | `src/services/document_processor.py` | PDF (pdfplumber + PyMuPDF/Tesseract OCR fallback) + DOCX (python-docx) text extraction, LLM-based field parsing with JSON mode, three-stage JSON repair pipeline |
| **Question Gen** | `src/services/question_generator.py` | Pure-LLM and hybrid question generation |
| **Answer Eval** | `src/services/answer_evaluator.py` | LLM-as-judge scoring, hallucination check, report aggregation |
| **Semantic Match** | `src/services/semantic_matcher.py` | sentence-transformers (`all-MiniLM-L6-v2`, 384-dim, CPU) resume-JD matching with LLM qualitative sidecar (hybrid mode via Groq); embedding inference offloaded via `asyncio.to_thread` |
| **Question Bank** | `src/services/question_bank.py` | Loads/indexes JSONL files from `questionBank/domains/` |
| **Hybrid Selector** | `src/services/hybrid_question_selector.py` | Picks bank questions + identifies uncovered skills for LLM gap-fill |
| **PDF Generator** | `src/services/pdf_generator.py` | ReportLab single-page scrollable PDF report |
| **Session Repo** | `src/services/session_repository.py` | Async MongoDB CRUD for interview sessions (save/load/delete/list) |
| **Prompts** | `src/services/prompts.py` | All LLM prompt templates (resume parsing, question gen, evaluation, match assessment) |
| **LLM Base** | `src/providers/llm/base.py` | `BaseLLMProvider` ABC, `GenerationConfig` dataclass (includes `json_mode` field), `LLMResponse`, `Message`, provider enum |
| **LLM Factory** | `src/providers/llm/factory.py` | `LLMProviderFactory` -- creates Groq/Ollama/vLLM/OpenAI-compatible providers from `models.yaml`, with health-check fallback |
| **LLM Groq** | `src/providers/llm/groq_provider.py` | Groq Cloud chat completions via httpx; supports `json_mode` (`response_format`), recovers `failed_generation` from 400 `json_validate_failed` errors |
| **LLM Ollama** | `src/providers/llm/ollama_provider.py` | Ollama `/api/chat` integration |
| **LLM vLLM** | `src/providers/llm/vllm_provider.py` | OpenAI-compatible vLLM provider |
| **STT Base** | `src/providers/stt/base.py` | `BaseSTTProvider` ABC, `TranscriptionResult`, `TranscriptionSegment`, `STTProvider` enum, `WhisperModel` enum |
| **STT Factory** | `src/providers/stt/__init__.py` | Unified config-aware STT factory (`get_stt_provider_async`); routes to Groq Whisper, faster-whisper, or OpenAI Whisper |
| **STT Groq** | `src/providers/stt/groq_whisper_provider.py` | Cloud STT via Groq Whisper API (multipart POST); models: `whisper-large-v3-turbo`, `whisper-large-v3` |
| **STT FasterWhisper** | `src/providers/stt/faster_whisper_provider.py` | Local CTranslate2 Whisper, auto CUDA/CPU fallback |
| **STT Whisper** | `src/providers/stt/whisper_provider.py` | Original OpenAI Whisper (fallback) |
| **TTS Base** | `src/providers/tts/base.py` | `BaseTTSProvider` ABC, `SynthesisResult`, `VoiceInfo`, `TTSProvider` enum |
| **TTS Factory** | `src/providers/tts/__init__.py` | Unified config-aware TTS factory (`get_tts_provider_async`); routes to Groq TTS, Coqui XTTS, or pyttsx3 |
| **TTS Groq** | `src/providers/tts/groq_tts_provider.py` | Cloud TTS via Groq Orpheus API; auto-chunks text >200 chars, concatenates WAV segments. Voices: autumn, diana, hannah (F), austin, daniel, troy (M) |
| **TTS Coqui** | `src/providers/tts/coqui_xtts_provider.py` | Local Coqui XTTS v2 (~1.8 GB weights, 24 kHz output) |
| **TTS pyttsx3** | `src/providers/tts/pyttsx3_provider.py` | System TTS via pyttsx3 (SAPI5/espeak), runs in thread pool executor |
| **Report Storage** | `src/providers/report_storage/` | Abstract base + local filesystem + S3 report storage |
| **Frontend** | Separate repo: `HackGeniX-hf-space/app.py` | Gradio tabbed UI (Login, Documents, Interviews, Live Session, Reports, Admin) deployed on HuggingFace Spaces |

## Router Mounting

All routers are mounted in `src/main.py` via `create_app()`:

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
       -> OCR fallback: if pdfplumber extracts <50 chars, tries PyMuPDF + Tesseract OCR
       -> SHA256 cache check in .cache/parsed_documents/
       -> if miss: LLM parse via RESUME_EXTRACTION_PROMPT (json_mode=True)
       -> JSON repair pipeline (3 stages):
            1. Direct json.loads()
            2. _repair_json() -> fixes trailing commas, control chars, inline math expressions
            3. _close_truncated_json() -> auto-closes unbalanced brackets for truncated output
       -> If parse fails: retry with temperature=0.0
       -> normalize field names (contact/contact_info/personal_info, etc.)
       -> return ParsedResume
  -> save to MongoDB resumes collection
  -> return ResumeUploadResponse
```

### 2. Interview Session Lifecycle

```
POST /api/v1/sessions/start  {resume_id, jd_id, config}
  -> Fetch real resume/JD from MongoDB
  -> InterviewOrchestrator.start_interview()
       -> SemanticMatcher.match(resume, jd)  (embedding via asyncio.to_thread + optional LLM sidecar)
            -> Store match_analysis on session
       -> HybridQuestionSelector.select_questions()
            -> QuestionBankService: load JSONL, filter by domain/stage/difficulty
            -> Score by skill overlap with JD+resume, enforce category diversity
            -> Return (selected_bank_questions, uncovered_skills)
       -> QuestionGenerator.generate_questions_hybrid(match_analysis=...)
            -> Enhance bank questions with LLM (batch or single)
            -> Generate gap-fill questions for uncovered skills
            -> match_context injected into all 4 stage prompts
       -> Create InterviewSession (in-memory _sessions dict + MongoDB via SessionRepository)
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
  -> GroqWhisperSTTProvider.transcribe()  (cloud, via Groq Whisper API)
  -> Return {text, language, confidence}

POST /api/v1/voice/synthesize  {text}
  -> GroqTTSProvider.synthesize()  (cloud, via Groq Orpheus API)
  -> Auto-chunks text >200 chars, concatenates WAV segments
  -> Return audio bytes

POST /api/v1/voice/transcribe/interview  {audio, session_id}
  -> transcribe_with_interview_context()  (adds technical term prompts)
  -> Return transcript
```

### 4. JSON Mode & Repair Pipeline (LLM responses)

All structured LLM calls (resume parsing, JD parsing, match assessment) use `GenerationConfig(json_mode=True)`, which triggers `response_format: {"type": "json_object"}` on the Groq API.

**Defense-in-depth layers:**

1. **Prompt** -- explicitly instructs the model to never write math expressions in JSON values
2. **Groq JSON mode** -- API-level enforcement of valid JSON structure
3. **Groq 400 recovery** -- if Groq returns HTTP 400 with `json_validate_failed`, the provider extracts the `failed_generation` text and returns it as an `LLMResponse` for caller-side repair
4. **`_repair_json()`** -- fixes trailing commas, control characters, evaluates inline math (e.g. `9.31 / 25` -> `0.3724`)
5. **`_close_truncated_json()`** -- auto-closes unbalanced `[]`/`{}` for truncated output
6. **Retry** -- second attempt with `temperature=0.0` if all parse attempts fail

## Port / URL Conventions

| Service | Default URL | Config |
|---------|------------|--------|
| FastAPI backend (local) | `http://localhost:8000` | `uvicorn src.main:app --port 8000` |
| FastAPI backend (prod) | `https://hackgenix-production.up.railway.app` | Railway auto-deploys, `$PORT` env var |
| Gradio frontend (prod) | `https://huggingface.co/spaces/rs2803/HackGeniX` | HF Spaces auto-deploys |
| Groq Cloud API | `https://api.groq.com/openai/v1` | `GROQ_API_URL` env var |
| MongoDB Atlas | connection string | `MONGODB_URI` env var |
| Swagger docs | `http://localhost:8000/docs` | Auto-generated (debug mode only) |
| ReDoc | `http://localhost:8000/redoc` | Auto-generated (debug mode only) |

## Auth System

- **Algorithm:** JWT HS256, 60-minute expiry
- **Secret:** `JWT_SECRET_KEY` env var (default: `"your-super-secret-key-change-in-production"` -- **must be overridden in production**)
- **Frontend generates tokens client-side** using PyJWT
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
- `get_session_repository()` -- `src/services/session_repository.py`
- `get_question_bank_service()` -- `src/services/question_bank.py`
- `get_hybrid_question_selector()` -- `src/services/hybrid_question_selector.py`
- `get_llm_provider()` (async) / `get_llm_provider_sync()` -- `src/providers/llm/factory.py`
- `get_stt_provider()` / `get_stt_provider_async()` -- `src/providers/stt/__init__.py` (unified config-aware factory)
- `get_tts_provider()` / `get_tts_provider_async()` -- `src/providers/tts/__init__.py` (unified config-aware factory)

**Eager loading at startup** (in `lifespan()` handler):
1. `await asyncio.to_thread(get_semantic_matcher)` -- loads the SentenceTransformer embedding model in a thread to avoid blocking the event loop
2. `tts = await get_tts_provider_async()` then `await tts.ensure_loaded()` -- loads TTS model (instant for Groq TTS, ~30-60s for Coqui XTTS)

**Gotcha:** Singletons are module-level globals. Server restart is the only way to force re-initialization. Hot reloading (uvicorn `--reload`) can cause stale references or duplicate instances.

## Model Configuration

All model selection is driven by `config/models.yaml` with no code changes required:

```yaml
providers:
  llm:
    provider: "groq"               # Options: vllm, ollama, llamacpp, openai-compatible, groq
    model: "llama-3.1-8b-instant"
    max_context_length: 8192

  embeddings:
    provider: "sentence-transformers"
    model: "sentence-transformers/all-MiniLM-L6-v2"  # ~80MB, CPU-friendly for cloud
    dimensions: 384
    device: "cpu"

  stt:
    provider: "groq-whisper"       # Options: whisper, faster-whisper, groq-whisper
    model: "whisper-large-v3"
    language: "en"

  matching:
    provider: "groq"               # LLM sidecar for hybrid resume-JD matching
    model: "llama-3.1-8b-instant"
    enabled: true                  # false = pure embedding, true = hybrid
    temperature: 0.1

  tts:
    provider: "groq-tts"           # Options: coqui-xtts, pyttsx3, groq-tts
    model: "canopylabs/orpheus-v1-english"
    voice: "troy"                  # Voices: autumn, diana, hannah (F) | austin, daniel, troy (M)
```

Environment variable overrides are supported via `Settings` fields: `PROVIDER_LLM_MODEL`, `PROVIDER_EMBEDDINGS_MODEL`, `PROVIDER_STT_MODEL`, `PROVIDER_TTS_PROVIDER`.

## Directory Layout

```
HackGeniX/
  Procfile                         # Railway: uvicorn start command with $PORT
  Aptfile                          # Railway: tesseract-ocr system packages for OCR
  requirements.txt                 # Python dependencies
  config/
    models.yaml                    # LLM/STT/TTS/embeddings/matching provider configuration
  src/
    main.py                        # FastAPI app, CUDA DLL setup, eager-load embeddings+TTS, router mounting, lifespan
    core/
      config.py                    # Settings (pydantic-settings), load_model_config(), Groq/Ollama/vLLM config
      database.py                  # Motor MongoDB client, collection accessors
      storage.py                   # S3/local storage client
      auth.py                      # JWT encode/decode, get_current_user
      permissions.py               # Role-permission matrix, require_*() deps
    models/
      documents.py                 # ParsedResume, ParsedJobDescription, MatchResult
      interview.py                 # InterviewSession, InterviewConfig, enums, request/response
      report.py                    # FullInterviewReport, ScoreBreakdown, HiringRecommendation
      question_bank.py             # BankQuestion, EnrichedQuestion, QuestionCategory, domains
      auth.py                      # AuthenticatedUser, UserRole, TokenResponse
    services/
      interview_orchestrator.py    # Central session controller
      question_generator.py        # LLM + hybrid question generation
      document_processor.py        # PDF/DOCX parsing, OCR fallback, JSON mode, 3-stage JSON repair
      answer_evaluator.py          # LLM-as-judge evaluation
      pdf_generator.py             # ReportLab PDF generation
      semantic_matcher.py          # Embedding-based resume-JD match + LLM sidecar
      question_bank.py             # JSONL question bank loader
      hybrid_question_selector.py  # Bank + LLM question selection
      prompts.py                   # All LLM prompt templates
      session_repository.py        # Async MongoDB session CRUD
    api/
      health.py                    # GET /health, GET /health/detailed
      documents.py                 # Resume + JD upload, list, delete, match
      sessions.py                  # Interview session CRUD + answer submission
      interviews.py                # Interview scheduling (partially implemented)
      questions.py                 # Question generation + evaluation endpoints
      voice.py                     # STT + TTS endpoints
      reports.py                   # Report retrieval + PDF download
      middleware.py                # Auth middleware
    providers/
      llm/
        base.py                    # BaseLLMProvider ABC, GenerationConfig (json_mode), LLMResponse
        factory.py                 # LLMProviderFactory: Groq/Ollama/vLLM/OpenAI-compatible
        groq_provider.py           # Groq Cloud chat completions, json_mode, 400 recovery
        ollama_provider.py         # Ollama /api/chat integration
        vllm_provider.py           # OpenAI-compatible vLLM provider
      stt/
        __init__.py                # Unified config-aware STT factory
        base.py                    # BaseSTTProvider ABC, TranscriptionResult, enums
        groq_whisper_provider.py   # Groq Cloud Whisper STT
        faster_whisper_provider.py # CTranslate2 local Whisper
        whisper_provider.py        # Original OpenAI Whisper fallback
      tts/
        __init__.py                # Unified config-aware TTS factory
        base.py                    # BaseTTSProvider ABC, SynthesisResult, enums
        groq_tts_provider.py       # Groq Cloud Orpheus TTS
        coqui_xtts_provider.py     # Local Coqui XTTS v2
        pyttsx3_provider.py        # System TTS via pyttsx3
      embeddings/
        __init__.py                # Empty; embedding logic lives in semantic_matcher.py
      report_storage/
        base.py                    # Abstract report storage
        local_provider.py          # Filesystem report storage
        s3_provider.py             # S3 report storage
  questionBank/
    domains/                       # JSONL files per technical domain
  storage/                         # Local file storage fallback
  .cache/
    parsed_documents/              # SHA256-keyed document parse cache
  .env                             # Environment variables (not committed)
```

**57 Python files across `src/`.** The heaviest directory is `src/services/`.
