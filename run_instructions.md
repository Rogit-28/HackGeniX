# HackGeniX AI Interviewer - Run Instructions

## Prerequisites

1. **Python 3.11+** installed
2. **MongoDB Atlas** configured (connection string in `.env`)
3. **Ollama** running locally for LLM (default: `http://localhost:11434`)
4. Virtual environment set up with dependencies installed

## Quick Start

### 1. Activate Virtual Environment

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows CMD
.venv\Scripts\activate.bat
```

### 2. Start Backend Server

Open a terminal and run:

```powershell
cd C:\Users\rogit\dev\HackGeniX
.venv\Scripts\python.exe -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

**Wait for startup to complete** (approximately 30-60 seconds). You should see:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Verify health check:
```powershell
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy", "mongodb": true, "storage": true, "version": "0.1.0"}
```

### 3. Start Frontend Server

Open a **new terminal** and run:

```powershell
cd C:\Users\rogit\dev\HackGeniX
x```

**Wait for startup** (approximately 10-15 seconds). You should see:
```
Running on local URL:  http://0.0.0.0:7860
```

### 4. Access the Application

- **Frontend UI**: http://localhost:7860
- **Backend API Docs**: http://localhost:8000/docs
- **Backend Health**: http://localhost:8000/health

## URLs Summary

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost:7860 | Gradio Web UI |
| Backend API | http://localhost:8000 | FastAPI Server |
| API Docs | http://localhost:8000/docs | Swagger UI |
| ReDoc | http://localhost:8000/redoc | Alternative API Docs |

## Environment Variables

Key settings in `.env`:

```env
# MongoDB
MONGODB_URI=mongodb+srv://...

# JWT Authentication
JWT_SECRET_KEY=your-super-secret-key-change-in-production
AUTH_ENABLED=true

# Ollama LLM
OLLAMA_API_URL=http://localhost:11434

# Storage (uses local filesystem by default if S3/MinIO unavailable)
S3_ENDPOINT_URL=http://localhost:9000
```

## Stopping the Servers

### Stop individual servers
Press `Ctrl+C` in each terminal window.

### Stop all Python processes (PowerShell)
```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
```

## Troubleshooting

### Backend won't start
1. Check MongoDB connection: Ensure MongoDB Atlas is accessible
2. Check port 8000: Make sure nothing else is using it
3. Check logs for errors in the terminal

### Frontend won't connect to backend
1. Ensure backend is running and healthy first
2. Check backend is on port 8000
3. Check browser console for CORS errors

### LLM parsing fails
1. Ensure Ollama is running: `curl http://localhost:11434/api/tags`
2. Check if model is pulled: `ollama list`
3. Default model is `llama3.2` - pull if needed: `ollama pull llama3.2`

### Resume/JD parsing takes too long
- LLM parsing can take 30-120 seconds depending on document size
- The frontend has a 120-second timeout for uploads
- Check Ollama logs if parsing consistently fails

## Development Mode

For hot-reload during development:

```powershell
# Backend with auto-reload (already enabled with --reload flag)
.venv\Scripts\python.exe -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (Gradio has built-in hot reload)
.venv\Scripts\python.exe frontend/app.py
```

## Running Tests

```powershell
.venv\Scripts\python.exe -m pytest tests/ -v --ignore=tests/test_semantic_matcher.py
```
