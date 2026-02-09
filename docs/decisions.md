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
**Decision:** Use BAAI/bge-large-en-v1.5 via sentence-transformers for resume-JD matching.  
**Rationale:** State-of-the-art embedding model for semantic similarity. Runs locally, no API calls. The weighted scoring (semantic 35%, skills 40%, experience 25%) in `src/services/semantic_matcher.py` provides a nuanced match beyond simple keyword overlap.  
**Tradeoff:** Model is ~1.3GB. First load takes several seconds. Stays in memory as a singleton.

### MongoDB Atlas over local MongoDB
**Decision:** Use MongoDB Atlas (cloud) instead of requiring local MongoDB installation.  
**Rationale:** Zero local setup for new contributors. Free tier is sufficient for development. Motor (async driver) integrates well with FastAPI.  
**Tradeoff:** Requires internet connection. DNS resolution issues are common (see `known-issues.md`). Connection string contains credentials.

### In-memory session storage
**Decision:** `InterviewOrchestrator` stores active sessions in a Python dict (`_sessions`).  
**Rationale:** Simplicity. No ORM, no cache layer, no serialization overhead. Sessions are written to MongoDB for persistence but reads during active interviews come from memory for speed.  
**Tradeoff:** Sessions lost on server restart. No multi-process scaling. MongoDB records survive but there is no reload mechanism. This is the most significant architectural limitation for production.

### Client-side JWT generation
**Decision:** The Gradio frontend generates JWT tokens locally using PyJWT.  
**Rationale:** No login endpoint, no user database, no OAuth flow needed. For development, this removes all auth friction -- the Admin panel has a "Generate Token" button. The shared secret is hardcoded.  
**Tradeoff:** Not a real auth system. Any client with the secret can forge tokens. Must be replaced with server-side token issuance for production.

### Hybrid question bank (70% curated / 30% LLM)
**Decision:** Interview questions come from a mix of curated JSONL bank and LLM-generated questions.  
**Rationale:** Curated questions have known quality and coverage. LLM fills gaps for skills not in the bank. The `HybridQuestionSelector` (`src/services/hybrid_question_selector.py`) auto-detects relevant domains from the JD text, then the `QuestionGenerator` enhances bank questions with LLM personalization.  
**Tradeoff:** More complex than pure-LLM generation. Bank questions need manual curation per domain. The 70/30 ratio is configurable via `InterviewConfig.bank_ratio`.

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

### OCR fallback (pytesseract)
**What:** Scanned-PDF support via Tesseract OCR.  
**Why dropped:** Added complexity, large dependency (Tesseract binary), and the primary use case is machine-readable PDFs. Removed during merge cleanup. Can be re-added if needed.

### certifi SSL override
**What:** Patched Python's SSL certificate bundle to fix MongoDB Atlas connection issues on certain systems.  
**Why dropped:** Fragile workaround. The real fix is ensuring the system's CA certificates are up to date. Removed during merge cleanup.

### LLM qualitative sidecar in semantic matcher
**What:** Added an LLM call alongside the embedding-based matching to generate qualitative commentary on resume-JD fit.  
**Why dropped:** Added latency and LLM cost to every match operation. The semantic matcher's quantitative scores are sufficient for the current use case. Removed during merge cleanup. The code existed in commit `ee8e67d`.

### Expanded resume models (Project, Research, Publication)
**What:** Richer `ParsedResume` with dedicated fields for projects, research papers, and publications.  
**Why dropped:** The 3B LLM couldn't reliably extract these fields. Simpler model with `experience` and `certifications` is more robust. Removed during merge cleanup.
