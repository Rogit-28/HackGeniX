# Setup Guide

## Prerequisites

| Dependency | Version | Notes |
|-----------|---------|-------|
| Python | 3.11+ | Tested on 3.11 |
| Ollama | Latest | Must be running before backend starts |
| MongoDB Atlas | (cloud) | Free tier works; need connection string |
| Git | Any | For cloning |

**Optional:** CUDA-capable GPU for faster STT (faster-whisper). Falls back to CPU automatically.

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

Edit `config/models.yaml` to configure LLM, STT, TTS providers:

```yaml
llm:
  provider: ollama              # ollama | vllm | openai-compatible
  model: qwen2.5:3b            # Model name as known to the provider
  temperature: 0.7
  max_tokens: 2048
  # fallback:                   # Optional fallback provider
  #   provider: vllm
  #   model: mistral-7b

embeddings:
  model: BAAI/bge-large-en-v1.5  # sentence-transformers model
  device: auto                    # auto | cpu | cuda

stt:
  provider: faster-whisper
  model: base                     # tiny | base | small | medium | large-v2
  device: auto                    # auto | cpu | cuda
  compute_type: auto              # auto | int8 | float16 | float32

tts:
  provider: pyttsx3
  rate: 150                       # Words per minute
  volume: 0.9                     # 0.0 - 1.0
```

**Environment variable overrides:** Any `models.yaml` field can be overridden with env vars. The `load_model_config()` function in `src/core/config.py` checks for env var equivalents.

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
3. **Backend healthy?** `curl http://localhost:8000/health` should return `{"status": "healthy"}`.
4. **Detailed health?** `curl http://localhost:8000/health/detailed` probes all 5 components.
5. **Frontend loads?** Open `http://localhost:7860` in browser.
6. **Login works?** Use the Admin panel to generate a JWT token, then paste it in the Login tab.
7. **Upload a resume.** Go to Documents tab, upload a PDF. Check that parsing completes.
8. **Create a JD.** Use the Documents tab or API to create a job description.
9. **Start interview.** Go to Live Session, select resume + JD, start session.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | Ensure `.venv` is activated and `pip install -r requirements.txt` completed |
| MongoDB connection timeout | Check `MONGODB_URI` in `.env`. Atlas may need IP whitelist (`0.0.0.0/0` for dev). DNS resolution issues are common -- see `known-issues.md` |
| Ollama 404 | Run `ollama pull qwen2.5:3b` and verify with `ollama list` |
| STT fails to load | First run downloads the Whisper model (~150MB for base). Needs internet access. GPU failures fall back to CPU automatically |
| TTS no audio | pyttsx3 needs system TTS engine (SAPI5 on Windows, espeak on Linux). Install espeak: `sudo apt install espeak` |
| Port conflict | Change port: `--port 8001` for backend, or set `GRADIO_SERVER_PORT` env var for frontend |
| JWT errors | Ensure `JWT_SECRET_KEY` matches between `.env` and `frontend/api_client.py` (default: `"your-super-secret-key-change-in-production"`) |
