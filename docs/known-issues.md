# Known Issues & Tech Debt

## Active Bugs

### Resume parsing silent-failure / cache-poisoning
**Location:** `src/services/document_processor.py` -- `parse_resume_with_llm()`
**Impact:** If the LLM returns unparseable JSON, the function silently returns a near-empty `ParsedResume` (just `raw_text`). This result is then cached by the SHA256 cache layer, meaning subsequent uploads of the same file will always return the bad parse without retrying the LLM.
**Fix:** Raise an exception on parse failure instead of returning an empty model. Add cache invalidation or skip caching on failure.

### cuBLAS/cuDNN fix not yet verified in production
**Location:** `src/main.py:6-26` -- NVIDIA DLL PATH registration
**Impact:** The PATH-based fix for `cublas64_12.dll` / `cudnn64_9.dll` has been verified in standalone Python tests but has NOT been confirmed working in the running FastAPI server. If it fails, faster-whisper will crash on CUDA inference and fall back would need manual intervention.
**Status:** Awaiting user verification.

### `models.yaml` TTS config mismatch
**Location:** `config/models.yaml:47-53`
**Impact:** The config file specifies `provider: "coqui-xtts"` for TTS, but the actual code uses `pyttsx3` (system TTS). The TTS config in `models.yaml` is not read by the TTS provider -- it's effectively ignored.
**Fix:** Either update `models.yaml` to reflect the actual pyttsx3 provider, or implement config-aware TTS factory similar to the STT factory.

## Resolved Bugs

### ~~`/match` endpoint returns placeholder data~~
**Resolved.** The `POST /api/v1/documents/match` endpoint now fetches real resume/JD from MongoDB and calls `SemanticMatcher.match()` with full hybrid scoring.

### ~~Sessions use mock data instead of MongoDB~~
**Resolved.** `start_interview()` in `src/api/sessions.py` now fetches real resume/JD from MongoDB using `mongodb_client.resumes.find_one()` and `mongodb_client.job_descriptions.find_one()`.

### ~~In-memory session storage (data loss on restart)~~
**Partially resolved.** `SessionRepository` (`src/services/session_repository.py`) now provides MongoDB write-through persistence. All session mutations are saved to MongoDB. `get_session()` falls back to loading from MongoDB if not in memory. Sessions survive server restarts. However, there is no bulk reload at startup -- sessions are loaded on-demand.

## Limitations

### STT accuracy
The configured STT model is `large-v3` on CUDA with `int8` compute type (see `config/models.yaml`). This provides good accuracy but is a large model (~1.5GB). Accuracy is still limited for:
- Highly specialized technical jargon
- Non-native English speakers in noisy environments

The `transcribe_with_interview_context()` method mitigates this by passing technical term prompts to Whisper.

### PyTorch is CPU-only
`torch.cuda.is_available()` returns `False` because the installed PyTorch is the CPU-only build. This means `sentence-transformers` (BAAI/bge-large-en-v1.5) runs embedding inference on CPU, not GPU. faster-whisper uses CTranslate2's own CUDA backend (separate from PyTorch) so STT still runs on GPU. Installing the CUDA PyTorch build would accelerate embedding inference but would add ~2GB to the venv.

### TTS quality
pyttsx3 uses the system TTS engine (SAPI5 on Windows, espeak on Linux). Voice quality is robotic compared to neural TTS. This is a conscious tradeoff -- see `decisions.md`.

### Single-process, no horizontal scaling
The singleton pattern and in-memory session storage mean the backend must run as a single process. No load balancing or multi-worker deployment is possible without architectural changes.

### No user management
There is no user registration, login, or user database. JWT tokens are generated client-side in the frontend (`frontend/api_client.py:59-78`). Any valid JWT with the correct secret is accepted. This is a development convenience, not a production auth system.

### No WebSocket support
The interview flow is request-response. There is no real-time push for question delivery or progress updates. The frontend polls for status.

## Tech Debt

### `interviews.py` vs `sessions.py` duplication
`src/api/interviews.py` and `src/api/sessions.py` are parallel systems that both manage interviews. `interviews.py` is a CRUD layer for scheduling; `sessions.py` is the live session controller. They use different MongoDB collections (`interviews` vs `interview_sessions`) and don't cross-reference each other. One should be consolidated or the relationship clarified.

### Global singletons with no cleanup
All services (`get_interview_orchestrator()`, `get_llm_provider()`, etc.) are module-level globals. There is no `shutdown()` or `cleanup()` mechanism. The `lifespan` handler in `src/main.py` handles startup but shutdown is minimal. With `--reload` in development, stale singleton references can cause subtle bugs.

### LLM response parsing is fragile
`QuestionGenerator` and `DocumentProcessor` parse JSON from LLM output by stripping markdown code blocks and attempting `json.loads()`. Small LLMs (qwen2.5:3b) frequently return malformed JSON, requiring retry logic and field-name normalization. There is no structured output enforcement (e.g., function calling or constrained decoding).

### No test suite
There are no unit tests, integration tests, or test fixtures. The `questionBank/` JSONL files serve as static test data for the question bank but there is no automated testing.

### Document parse cache has no eviction
The SHA256-based cache in `.cache/parsed_documents/` grows unbounded. No TTL, no size limit, no cleanup.

### PDF generation uses single-page design
`PDFReportGenerator` creates one long scrollable page rather than paginated output. This works for screen viewing and short reports but produces unwieldy PDFs for long interviews.

### Hardcoded database name
`interview_system` is hardcoded in `src/core/database.py`. Not configurable via env var.

### DNS flakiness with MongoDB Atlas
MongoDB Atlas connections occasionally fail with DNS resolution errors, especially on networks with restrictive DNS. The `MONGODB_URI` uses SRV records (`mongodb+srv://`) which require DNS lookups. No retry logic on connection failure.

### red_flags / green_flags not wired through data model
The LLM match assessment can return `risk_flags` and `strengths`, but these are stored as flat lists on `MatchResult`. There is no structured data model for individual flags (severity, category, evidence) and they are not surfaced in the frontend or PDF reports.
