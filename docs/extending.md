# Extending the System

## Add a New Question Domain

Question bank domains are JSONL files in `questionBank/domains/`. Each line is a JSON object representing one question.

### 1. Create the JSONL file

```
questionBank/domains/your_domain.jsonl
```

Each line:
```json
{
  "id": "your_domain_001",
  "question": "Explain how X works and when you would use it.",
  "domain": "your_domain",
  "difficulty": "medium",
  "skills": ["skill_a", "skill_b"],
  "expected_topics": ["topic_1", "topic_2"],
  "follow_up": "How would you optimize this in a production setting?"
}
```

**Fields:** `id` (unique), `question` (text), `domain` (matches filename), `difficulty` (easy/medium/hard/expert), `skills` (list), `expected_topics` (list), `follow_up` (optional).

### 2. Register domain keywords

Edit `src/models/question_bank.py` and add your domain to the `DOMAIN_KEYWORDS` dict:

```python
DOMAIN_KEYWORDS = {
    # ... existing domains ...
    "your_domain": ["keyword1", "keyword2", "keyword3"],
}
```

The `detect_domains_from_text()` function uses these keywords to auto-detect relevant domains from JD text.

### 3. Verify

The `QuestionBankService` (`src/services/question_bank.py`) auto-discovers JSONL files on first load. No registration needed beyond creating the file and adding keywords. Questions are auto-enriched with category (regex pattern matching), difficulty, and stage hints.

---

## Swap an LLM Provider

### Option A: Change the model in `config/models.yaml`

```yaml
llm:
  provider: ollama        # Change to: vllm, openai-compatible
  model: qwen2.5:3b      # Change to any model the provider supports
```

Restart the backend. The `LLMProviderFactory` reads this config and instantiates the right provider.

### Option B: Add a new provider type

1. Create `src/providers/llm/your_provider.py`
2. Extend `BaseLLMProvider` (`src/providers/llm/base.py`):

```python
from src.providers.llm.base import BaseLLMProvider, LLMResponse, Message, GenerationConfig

class YourProvider(BaseLLMProvider):
    def __init__(self, model: str, api_url: str, **kwargs):
        super().__init__(model)
        self.api_url = api_url

    async def generate(self, messages: List[Message], config: GenerationConfig = None) -> LLMResponse:
        # Call your LLM API
        # Return LLMResponse(content="...", model=self.model, usage={...})
        pass

    async def generate_stream(self, messages: List[Message], config: GenerationConfig = None):
        # Yield partial responses (optional, can raise NotImplementedError)
        pass

    async def health_check(self) -> bool:
        # Return True if the provider is reachable
        pass
```

3. Register in `src/providers/llm/factory.py`:

```python
# In LLMProviderFactory.create():
elif provider_type == "your-provider":
    from src.providers.llm.your_provider import YourProvider
    return YourProvider(model=model, api_url=api_url, **config)
```

4. Update `config/models.yaml`:
```yaml
llm:
  provider: your-provider
  model: your-model-name
  api_url: http://localhost:9999
```

---

## Add a New API Endpoint

### 1. Choose the router

Pick the appropriate router file in `src/api/`:
- `documents.py` -- document operations
- `sessions.py` -- interview session operations
- `questions.py` -- question/evaluation operations
- `voice.py` -- STT/TTS operations
- `reports.py` -- report operations
- Or create a new router file

### 2. Add the route

```python
# In src/api/your_router.py (or existing router)

@router.post("/your-endpoint")
async def your_endpoint(
    request: YourRequest,
    user: AuthenticatedUser = Depends(get_current_user),       # Auth required
    # OR for role-specific:
    user: AuthenticatedUser = Depends(require_role("admin")),
    # OR for permission-specific:
    user: AuthenticatedUser = Depends(require_permission("manage_interviews")),
):
    # Implementation
    return YourResponse(...)
```

### 3. If new router file, mount it

In `src/main.py`:
```python
from src.api import your_router
app.include_router(your_router.router, prefix="/api/v1/your-prefix")
```

### 4. Make it public (optional)

If the endpoint should not require auth, add the path prefix to the public paths list in `src/api/middleware.py`:

```python
PUBLIC_PATH_PREFIXES = [
    "/health",
    "/api/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/your-public-prefix",   # Add here
]
```

---

## Add a New Interview Stage

### 1. Add the enum value

In `src/models/interview.py`:
```python
class InterviewStage(str, Enum):
    introduction = "introduction"
    technical = "technical"
    behavioral = "behavioral"
    situational = "situational"
    closing = "closing"
    your_stage = "your_stage"       # Add here
```

### 2. Add question count to config

In `src/models/interview.py`, `InterviewConfig`:
```python
class InterviewConfig(BaseModel):
    # ... existing fields ...
    your_stage_questions: int = 3
```

### 3. Add stage prompt

In `src/services/prompts.py`, add to `QUESTION_GENERATION_PROMPTS`:
```python
QUESTION_GENERATION_PROMPTS = {
    # ... existing stages ...
    "your_stage": """Generate {count} your-stage interview questions...
    ... your prompt template ...
    """,
}
```

### 4. Update orchestrator stage flow

In `src/services/interview_orchestrator.py`, the `start_interview()` method builds questions per stage. Add your stage to the stage ordering and question generation loop. Search for the existing stage list and add yours in the appropriate position.

### 5. Add stage hint for question bank

In `src/models/question_bank.py`:
```python
class InterviewStageHint(str, Enum):
    # ... existing ...
    your_stage = "your_stage"
```

---

## Wire a New Frontend Tab

### 1. Add the tab in Gradio

In `frontend/app.py`, inside `create_app()` (around line 593), find the `gr.Tabs()` block and add:

```python
with gr.Tab("Your Tab"):
    # UI components
    your_input = gr.Textbox(label="Input")
    your_button = gr.Button("Submit")
    your_output = gr.Textbox(label="Output")
```

### 2. Add the handler function

Before `create_app()` (in the functions section, lines 1-592), add:

```python
def handle_your_feature(input_text, token):
    """Handler for your tab."""
    client = InterviewAPIClient(base_url="http://localhost:8000")
    client.set_token(token)
    response = client.session.post(
        f"{client.base_url}/api/v1/your-endpoint",
        json={"input": input_text},
        headers=client._get_headers()
    )
    return response.json()
```

### 3. Wire the event

Inside `create_app()`, after defining the components:

```python
your_button.click(
    fn=handle_your_feature,
    inputs=[your_input, token_state],
    outputs=[your_output]
)
```

The `token_state` is a `gr.State()` that holds the JWT token, shared across all tabs.

---

## Swap Storage Backend

The `StorageClient` (`src/core/storage.py`) auto-detects S3/MinIO availability and falls back to local filesystem. To force a specific backend:

```env
# In .env
STORAGE_TYPE=local    # Always use ./storage/
STORAGE_TYPE=s3       # Always use S3/MinIO
```

To add a new storage backend (e.g., GCS, Azure Blob), implement the same interface:
- `upload_bytes(path: str, data: bytes) -> str`
- `download_bytes(path: str) -> bytes`
- `delete_file(path: str) -> bool`
- `health_check() -> dict`

And update the `StorageClient.__init__()` to handle your backend type.

---

## Swap STT/TTS Provider

Same pattern as LLM providers. Implement the base interface:

**STT:** See `src/providers/stt/faster_whisper_provider.py` for the interface. Key methods: `transcribe()`, `detect_language()`, `get_model_info()`.

**TTS:** See `src/providers/tts/pyttsx3_provider.py` for the interface. Key methods: `synthesize()`, `get_provider_info()`, `configure()`.

Register your provider in the respective factory/singleton function and update `config/models.yaml`.
