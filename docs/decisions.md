# Design Decisions

## Technology Choices

### Ollama over vLLM for development
**Decision:** Use Ollama as the primary LLM provider during development.  
**Rationale:** Ollama is trivial to install on any OS (one binary), manages model downloads, and runs without GPU configuration. vLLM requires CUDA, has complex installation, and is designed for production serving. The `LLMProviderFactory` (`src/providers/llm/factory.py`) abstracts this -- switching to vLLM for production requires only a `config/models.yaml` change.  
**Tradeoff:** Ollama is slower and has less throughput than vLLM. Acceptable for development and demo.

### qwen2.5:3b as default model
**Decision:** Use a 3B parameter model.  
**Rationale:** Runs on consumer hardware (8GB RAM, no GPU required). Fast enough for interactive use. Qwen 2.5 has strong instruction-following for its size, which matters for the structured JSON outputs needed by `DocumentProcessor` and `QuestionGenerator`.  
**Tradeoff:** JSON output is frequently malformed, requiring retry logic and field-name normalization in `src/services/document_processor.py`. Larger models (7B+) would reduce parsing failures.

### pyttsx3 over neural TTS
**Decision:** Use pyttsx3 (system TTS) instead of Coqui, Bark, or cloud TTS.  
**Rationale:** Zero dependencies beyond the OS's built-in speech engine. No model downloads, no GPU, no API keys. Instant startup. The interview system prioritizes *having* TTS over *quality* of TTS.  
**Tradeoff:** Robotic voice quality. Not suitable for production candidate-facing use. Swapping to a neural TTS provider only requires implementing the base interface in `src/providers/tts/`.

### faster-whisper over OpenAI Whisper
**Decision:** Use CTranslate2-optimized faster-whisper instead of the original OpenAI Whisper.  
**Rationale:** 4x faster inference, lower memory usage, same model weights. Auto-detects CUDA and falls back to CPU. The `FasterWhisperSTTProvider` (`src/providers/stt/faster_whisper_provider.py`) wraps this cleanly.  
**Tradeoff:** CTranslate2 has occasional compatibility issues with specific CUDA versions. The auto-fallback to CPU handles this gracefully.

### sentence-transformers for semantic matching
**Decision:** Use BAAI/bge-large-en-v1.5 via sentence-transformers for resume-JD matching, with an optional LLM qualitative sidecar for hybrid scoring.
**Rationale:** State-of-the-art embedding model for semantic similarity. Runs locally, no API calls. Core-only weights (semantic 35%, skills 40%, experience 25%) provide a nuanced match beyond simple keyword overlap. When the LLM sidecar is enabled (`config/models.yaml` `matching.enabled: true`), hybrid weights apply (semantic 25%, skills 30%, experience 20%, llm_fit 25%) and the LLM generates transferable skills, risk flags, strengths, and experience quality assessments.
**Tradeoff:** Model is ~1.3GB. First load takes several seconds (mitigated by eager-loading at startup via `asyncio.to_thread`). Stays in memory as a singleton. LLM sidecar adds latency (~2-5s per match).

### MongoDB Atlas over local MongoDB
**Decision:** Use MongoDB Atlas (cloud) instead of requiring local MongoDB installation.  
**Rationale:** Zero local setup for new contributors. Free tier is sufficient for development. Motor (async driver) integrates well with FastAPI.  
**Tradeoff:** Requires internet connection. DNS resolution issues are common (see `known-issues.md`). Connection string contains credentials.

### Write-through session persistence with in-memory cache
**Decision:** `InterviewOrchestrator` stores active sessions in a Python dict (`_sessions`) and writes through to MongoDB via `SessionRepository` (`src/services/session_repository.py`) on every mutation. Reads check the in-memory dict first, then fall back to MongoDB.  
**Rationale:** Low-latency reads during active interviews (dict lookup), with durability for crash recovery and server restarts. `SessionRepository` is a simple async CRUD layer using `mongodb_client.interview_sessions` with upsert-on-save semantics and UUID-as-`_id`.  
**Tradeoff:** Still single-process — two server instances would have inconsistent in-memory caches. The MongoDB fallback only helps after a restart, not for load balancing. Write amplification: every `submit_answer()` call writes the entire session document.

### Client-side JWT generation
**Decision:** The Gradio frontend generates JWT tokens locally using PyJWT.  
**Rationale:** No login endpoint, no user database, no OAuth flow needed. For development, this removes all auth friction -- the Admin panel has a "Generate Token" button. The shared secret is hardcoded.  
**Tradeoff:** Not a real auth system. Any client with the secret can forge tokens. Must be replaced with server-side token issuance for production.

### Hybrid question bank (70% curated / 30% LLM)
**Decision:** Interview questions come from a mix of curated JSONL bank and LLM-generated questions.  
**Rationale:** Curated questions have known quality and coverage. LLM fills gaps for skills not in the bank. The `HybridQuestionSelector` (`src/services/hybrid_question_selector.py`) auto-detects relevant domains from the JD text, then the `QuestionGenerator` enhances bank questions with LLM personalization.  
**Tradeoff:** More complex than pure-LLM generation. Bank questions need manual curation per domain. The 70/30 ratio is configurable via `InterviewConfig.bank_question_ratio`.

### LLM-as-judge with hallucination check
**Decision:** `AnswerEvaluator` uses the LLM to score answers, then validates the recommendation against the calculated score.  
**Rationale:** Small LLMs sometimes generate confident but wrong evaluations. The hallucination check (`src/services/answer_evaluator.py`) catches cases where the LLM says "strong hire" but the calculated score is below threshold (or vice versa). The override ensures the final recommendation is consistent with the numbers.  
**Tradeoff:** The override is a blunt instrument. It can mask nuanced LLM reasoning. But for a 3B model, consistency is more important than nuance.

### ReportLab for PDF generation
**Decision:** Use ReportLab to generate interview report PDFs.  
**Rationale:** Pure Python, no external binaries (unlike wkhtmltopdf or headless Chrome). Full control over layout. The single-page scrollable design (`src/services/pdf_generator.py`) avoids pagination complexity.  
**Tradeoff:** Manual layout code is verbose (724 lines). No template system. Changes require modifying Python code.

### Gradio for frontend
**Decision:** Use Gradio instead of React/Next.js/etc.  
**Rationale:** Python-only stack. No separate build step, no Node.js dependency. Rapid prototyping with built-in components for file upload, audio, and tabbed layouts. Single `app.py` file.  
**Tradeoff:** Limited UI customization. No fine-grained component control. The UI is functional but not polished.

## What Was Tried and Dropped

*Nothing has been permanently dropped.* All features previously flagged as "removed during merge cleanup" (LLM sidecar, expanded resume models, OCR fallback, certifi SSL) were either restored in Session 1 or confirmed to still be present in the codebase:

- **OCR fallback (pytesseract):** Still active in `src/services/document_processor.py:75-105`. Falls back to Tesseract if pdfplumber returns < 50 chars. Requires PyMuPDF + pytesseract + Tesseract binary.
- **certifi SSL override:** Still active in `src/core/database.py:9,50`. Motor client uses `tlsCAFile=certifi.where()` for MongoDB Atlas TLS.
- **LLM qualitative sidecar:** Restored to `src/services/semantic_matcher.py`. Active when `config/models.yaml` `matching.enabled: true`. See "sentence-transformers" decision above.
- **Expanded resume models (Project, Research):** Restored to `src/models/documents.py`. The 3B LLM's extraction quality varies, but the fields exist and are populated when the LLM cooperates.

---

## Decisions Added in Sessions 3-6

### Config-aware STT factory (Session 3)
**Decision:** Replace hardcoded provider imports with a unified `get_stt_provider()` / `get_stt_provider_async()` factory in `src/providers/stt/__init__.py` that reads `config/models.yaml` for provider, model, device, compute_type, and language.  
**Rationale:** STT config was scattered: `voice.py` imported one provider, `health.py` imported another, model/device were hardcoded per call-site. The factory centralizes all of this into one singleton with one config source.  
**Tradeoff:** Adds a level of indirection. The old provider-specific factories are still exported for backward compatibility but should not be used directly.

### NVIDIA DLL PATH registration over os.add_dll_directory (Session 4)
**Decision:** Prepend `nvidia\cublas\bin` and `nvidia\cudnn\bin` to `os.environ["PATH"]` at the top of `src/main.py` (before any other imports), instead of using Python's `os.add_dll_directory()`.  
**Rationale:** ctranslate2 loads CUDA kernels at inference time via a mechanism that only checks the system PATH, not Python's DLL directory registry. `os.add_dll_directory()` was tried first and does not work for this case.  
**Tradeoff:** Pollutes the system PATH for the process. Windows-only code path (guarded by `sys.platform == "win32"`).

### Adversarial evaluation prompts with inline rubric generation (Session 4)
**Decision:** Rewrite both `ANSWER_EVALUATION_PROMPT` and `BEHAVIORAL_EVALUATION_PROMPT` in `src/services/prompts.py` with adversarial calibration anchors and inline rubric generation. Server-side weighted overall enforcement in `answer_evaluator.py`.  
**Rationale:** The 3B LLM tends toward score inflation (clustering around 70-80). Adversarial anchors (explicit examples of what a 30, 50, 70, 90 looks like) and server-side recomputation of overall scores from components reduce this bias.  
**Tradeoff:** Longer prompts consume more context window. Temperature lowered from 0.3 to 0.2, max_tokens raised from 1024 to 1536 to accommodate rubric output.

### MongoDB write-through session persistence (Session 5)
**Decision:** Add `SessionRepository` (`src/services/session_repository.py`) for async MongoDB CRUD, and wire it into `InterviewOrchestrator` as a write-through layer with fallback reads.  
**Rationale:** Sessions were lost on server restart. Write-through preserves low-latency in-memory reads for active interviews while ensuring all mutations are durable.  
**Tradeoff:** See "Write-through session persistence" decision above. Every mutation writes the full session document.

### Match-aware question generation (Session 5)
**Decision:** Run `SemanticMatcher.match()` at interview start, store the result on `session.match_analysis`, and thread it into all 4 stage question generation prompts via `{match_context}`.  
**Rationale:** Generic questions waste interview time. Match analysis tells the LLM exactly which skills are matched/missing/transferable, what risk flags exist, and the candidate's experience quality, allowing stage-specific targeting (e.g., screening probes missing skills, technical tests matched skills for depth).  
**Tradeoff:** Adds ~3-10s to interview start (embedding + optional LLM sidecar). If the matcher fails, interview proceeds without match context (graceful degradation).

### asyncio.to_thread for blocking ML inference (Session 6)
**Decision:** Wrap SentenceTransformer model load and embedding inference in `asyncio.to_thread()` in `src/services/semantic_matcher.py`, and eager-load the model at server startup in `src/main.py:lifespan()`.  
**Rationale:** The embedding model load (~3-5s) and inference block the async event loop, causing all concurrent requests to time out. `asyncio.to_thread()` offloads to a thread pool. Eager-loading at startup means the first interview request doesn't pay the model load cost.  
**Tradeoff:** Thread pool adds slight overhead. The model is still loaded once as a singleton. Eager-load adds ~10-30s to server startup time.
