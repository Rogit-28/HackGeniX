# Setup Guide

## Prerequisites

| Dependency | Version | Notes |
|-----------|---------|-------|
| Python | 3.11+ | Tested on 3.11 |
| Ollama | Latest | Must be running before backend starts |
| MongoDB Atlas | (cloud) | Free tier works; need connection string |
| Git | Any | For cloning |

**Optional but recommended:** CUDA-capable GPU for STT (faster-whisper) and semantic matching (sentence-transformers). Both fall back to CPU automatically, but CUDA is significantly faster.

**CUDA prerequisites (if using GPU):**
```bash
# Required for faster-whisper large-v3 on CUDA:
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```
These provide `cublas64_12.dll` and `cudnn64_9.dll` which ctranslate2 needs at inference time. The backend's `src/main.py` auto-registers these DLL paths on Windows at startup. No system-wide CUDA Toolkit installation is required.

## Installation

```bash
git clone <repo-url> HackGeniX
cd HackGeniX

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/Mac)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Environment Variables

Create a `.env` file in the project root:

```env
# MongoDB Atlas connection string (required)
MONGODB_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/?retryWrites=true&w=majority

# Ollama (defaults shown)
OLLAMA_API_URL=http://localhost:11434

# vLLM (optional, if using vLLM instead of Ollama)
# VLLM_API_URL=http://localhost:8001

# JWT auth secret -- must match between frontend and backend
JWT_SECRET_KEY=your-super-secret-key-change-in-production

# Storage: "local" or "s3"
STORAGE_TYPE=local

# S3/MinIO (only if STORAGE_TYPE=s3)
# S3_ENDPOINT_URL=http://localhost:9000
# S3_ACCESS_KEY=minioadmin
# S3_SECRET_KEY=minioadmin
# S3_BUCKET_NAME=hackgenix
# S3_REGION=us-east-1
```

## Model Configuration

Edit `config/models.yaml` to configure LLM, STT, TTS, embeddings, and matching providers:

```yaml
providers:
  llm:
    provider: "ollama"              # ollama | vllm | openai-compatible
    model: "qwen2.5:3b"            # Model name as known to the provider
    max_context_length: 8192

  embeddings:
    provider: "sentence-transformers"
    model: "BAAI/bge-large-en-v1.5"   # ~1.3GB, 1024 dimensions
    dimensions: 1024
    device: "cuda"                     # cuda | cpu

  stt:
    provider: "faster-whisper"         # faster-whisper | whisper
    model: "large-v3"                  # tiny | base | small | medium | large-v2 | large-v3
    compute_type: "int8"               # int8 | float16 | int8_float16 | float32
    device: "cuda"                     # cuda | cpu
    language: "en"                     # ISO code or "auto" for detection
    vad_filter: true                   # Voice activity detection (recommended)

  matching:
    provider: "ollama"                 # LLM sidecar for hybrid resume-JD matching
    model: "qwen2.5:3b"
    enabled: true                      # false = pure embedding, true = hybrid
    max_tokens: 1024
    temperature: 0.1

  tts:
    provider: "coqui-xtts"            # NOTE: actual code uses pyttsx3 regardless of this setting
    model: "tts_models/multilingual/multi-dataset/xtts_v2"
    device: "cuda"
```

> **Note:** The `tts` section in `models.yaml` currently has no effect. The code always uses pyttsx3 (system TTS). This is a known config-code mismatch (see `known-issues.md`).

## Pull the LLM Model

```bash
ollama pull qwen2.5:3b
```

Verify it's available:
```bash
ollama list
```

## Start the Servers

The backend and frontend are started separately in two terminals.

**Terminal 1 -- Backend (FastAPI):**
```bash
# Make sure .venv is activated
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 -- Frontend (Gradio):**
```bash
# Make sure .venv is activated
python -m frontend.app
```

## First-Run Checklist

1. **Ollama running?** `curl http://localhost:11434/api/tags` should list your model.
2. **MongoDB reachable?** Backend logs will show connection success/failure at startup.
3. **Embedding model loads?** On first backend start, the sentence-transformers model (`BAAI/bge-large-en-v1.5`, ~1.3GB) is downloaded and eager-loaded. Look for `"Loading embedding model (this may take a moment)..."` followed by `"Embedding model ready"` in the logs. **First run may take 30-60s** for model download + load. Subsequent starts take ~10-30s (load from cache).
4. **Backend healthy?** `curl http://localhost:8000/health` should return `{"status": "healthy"}`.
5. **Detailed health?** `curl http://localhost:8000/health/detailed` probes all 5 components.
6. **Frontend loads?** Open `http://localhost:7860` in browser.
7. **Login works?** Use the Admin panel to generate a JWT token, then paste it in the Login tab.
8. **Upload a resume.** Go to Documents tab, upload a PDF. Check that parsing completes.
9. **Create a JD.** Use the Documents tab or API to create a job description.
10. **Start interview.** Go to Live Session, select resume + JD, start session.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | Ensure `.venv` is activated and `pip install -r requirements.txt` completed |
| MongoDB connection timeout | Check `MONGODB_URI` in `.env`. Atlas may need IP whitelist (`0.0.0.0/0` for dev). DNS resolution issues are common -- see `known-issues.md` |
| Ollama 404 | Run `ollama pull qwen2.5:3b` and verify with `ollama list` |
| STT fails to load | First run downloads the Whisper model (~3GB for large-v3). Needs internet access. GPU failures fall back to CPU automatically |
| cuBLAS/cuDNN DLL not found | Install `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`. The backend registers DLL paths automatically on Windows. If the error persists, verify the DLLs exist: `.venv\Lib\site-packages\nvidia\cublas\bin\cublas64_12.dll` and `.venv\Lib\site-packages\nvidia\cudnn\bin\cudnn64_9.dll` |
| TTS no audio | pyttsx3 needs system TTS engine (SAPI5 on Windows, espeak on Linux). Install espeak: `sudo apt install espeak` |
| Port conflict | Change port: `--port 8001` for backend, or set `GRADIO_SERVER_PORT` env var for frontend |
| JWT errors | Ensure `JWT_SECRET_KEY` matches between `.env` and `frontend/api_client.py` (default: `"your-super-secret-key-change-in-production"`) |
