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

### ~~`models.yaml` TTS config mismatch~~
**Resolved.** The TTS factory in `src/providers/tts/__init__.py` now reads `config/models.yaml` `providers.tts` to select between Coqui XTTS v2 and pyttsx3. The config is no longer ignored.

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

### ~~PyTorch is CPU-only~~
**Resolved.** PyTorch is now `2.10.0+cu126` with CUDA 12.6 support. `torch.cuda.is_available()` returns `True`. The GPU is an NVIDIA RTX 4050 Laptop (6 GB VRAM).

### VRAM budget on 6 GB RTX 4050
With XTTS v2 (~1.8 GB), Ollama qwen2.5:3b (~2 GB), and faster-whisper large-v3 int8 (~1.5 GB on demand), VRAM is tight. Loading the embedding model (bge-large-en-v1.5, ~1.3 GB) on CUDA alongside XTTS caused a segfault/OOM during server startup. **Fix:** Embeddings are configured to run on CPU (`config/models.yaml` `providers.embeddings.device: "cpu"`). Embedding inference on CPU is still fast (~50-100ms per query) and frees VRAM for voice models. To experiment, swap `device: "cpu"` to `device: "cuda"` in `models.yaml` — but reduce other GPU tenants first (e.g., use a smaller STT model or move TTS to CPU).

### TTS quality and latency
Coqui XTTS v2 is the primary TTS provider, producing natural-sounding speech with optional voice cloning. With CUDA PyTorch installed, XTTS inference runs on GPU at ~7-8 s per utterance (RTF ~0.34x, i.e., ~3x faster than real-time). This is acceptable for interview questions. Without a `speaker_wav` reference audio, the model uses a built-in speaker embedding ("Claribel Dervla" by default). If the `TTS` pip package is not installed, the system falls back to pyttsx3 (system TTS), which is fast but robotic.

### TTS library compatibility patches (TTS 0.22.0 + transformers 4.57 + PyTorch 2.10)
Three files in `.venv/Lib/site-packages/TTS/` required manual patches to fix compatibility with newer `transformers` and `PyTorch`:

1. **`TTS/tts/layers/xtts/stream_generator.py`** (line 13-23) -- `BeamSearchScorer` was removed from `transformers`'s top-level exports in v4.50+. Fixed by importing from `transformers.generation.beam_search` instead.
2. **`TTS/utils/io.py`** (line 44) -- PyTorch 2.6+ changed `torch.load` to default to `weights_only=True`, but Coqui checkpoints contain pickle data. Fixed by adding `kwargs.setdefault("weights_only", False)`.
3. **`TTS/tts/layers/xtts/gpt_inference.py`** (line 9) -- `GPT2InferenceModel` extends `GPT2PreTrainedModel` but `PreTrainedModel` no longer inherits from `GenerationMixin` in transformers v4.50+, breaking `.generate()`. Fixed by adding `GenerationMixin` to the class inheritance.
4. **`TTS/tts/layers/xtts/xtts_manager.py`** (lines 5, 13, 17) -- `SpeakerManager.__init__` used `torch.load` without `weights_only=False`, and `speaker_names` property called `.keys()` on `dict_keys`. Fixed both.

**These patches will be lost if `TTS` is reinstalled.** If upgrading `TTS` or `transformers`, check whether these issues are fixed upstream first. A `postinstall` script or a `patches/` directory could automate this.

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
