# Known Issues & Tech Debt

## Active Bugs

### `/match` endpoint returns placeholder data
**Location:** `src/api/documents.py` -- `POST /api/v1/documents/match`  
**Impact:** Resume-JD matching via the API always returns hardcoded scores.  
**Root cause:** The `SemanticMatcher` service exists and works (`src/services/semantic_matcher.py`) but is not wired into this endpoint. The route handler returns a placeholder `MatchResult`.  
**Fix:** Fetch resume and JD from MongoDB, call `SemanticMatcher.match()`, return real scores.

### Sessions use mock data instead of MongoDB
**Location:** `src/api/sessions.py` -- `POST /api/v1/sessions/start`  
**Impact:** Starting an interview session does not fetch the actual resume/JD from MongoDB. It uses `_mock_resumes` and `_mock_job_descriptions` dicts hardcoded in the file.  
**Fix:** Replace mock lookups with MongoDB queries using `mongodb_client.resumes.find_one()` and `mongodb_client.job_descriptions.find_one()`.

### In-memory session storage (data loss on restart)
**Location:** `src/services/interview_orchestrator.py` -- `_sessions: Dict[str, InterviewSession]`  
**Impact:** Active interview sessions live only in the orchestrator's memory. If the backend restarts, all in-progress sessions are lost. MongoDB records exist but there is no recovery/reload mechanism.  
**Fix:** Add a startup routine that loads active sessions from MongoDB, or switch to DB-first reads.

## Limitations

### STT accuracy with small Whisper models
The default STT model is `base` (74M params). Accuracy is limited for:
- Technical jargon (framework names, acronyms)
- Non-native English speakers
- Noisy environments

The `transcribe_with_interview_context()` method mitigates this by passing technical term prompts to Whisper, but results are still approximate. Upgrading to `small` or `medium` model improves accuracy at the cost of speed and memory.

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

## Removed Features (from merge cleanup)

These features existed in earlier commits but were removed during the merge cleanup (`fcae581`):

- **LLM qualitative sidecar** in semantic matcher -- added hybrid LLM+embedding scoring, removed because the merge branch didn't include it
- **OCR fallback** for scanned PDFs -- used pytesseract, removed in merge
- **certifi SSL override** -- patched SSL cert bundle for MongoDB Atlas connection issues, removed in merge
- **Expanded resume models** (Project, Research, Publication) -- richer resume parsing, removed in merge
