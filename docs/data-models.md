# Data Models

## Pydantic Models

### Documents (`src/models/documents.py`)

**`ContactInfo`**
```
name: Optional[str]
email: Optional[str]
phone: Optional[str]
location: Optional[str]
linkedin: Optional[str]
github: Optional[str]
```

**`Education`**
```
institution: Optional[str]
degree: Optional[str]
field: Optional[str]
start_date: Optional[str]
end_date: Optional[str]
gpa: Optional[float]
```

**`Experience`**
```
company: Optional[str]
title: Optional[str]
location: Optional[str]
start_date: Optional[str]
end_date: Optional[str]
description: Optional[str]
highlights: List[str]
skills: List[str]
impact: List[str]
```

**`Project`**
```
name: Optional[str]
description: Optional[str]
tech_stack: List[str]
highlights: List[str]
skills: List[str]
impact: List[str]
url: Optional[str]
```

**`Research`**
```
title: Optional[str]
venue: Optional[str]
status: Optional[str]
highlights: List[str]
skills: List[str]
impact: List[str]
```

**`ParsedResume`**
```
contact: ContactInfo
summary: Optional[str]
skills: List[str]
experience: List[Experience]
education: List[Education]
certifications: List[str]
projects: List[Project]
research: List[Research]
soft_skills: List[str]
areas_of_interest: List[str]
extra_sections: Dict[str, Any]
languages: List[str]
entities: List[ParsedEntity]
raw_text: str                 # Full extracted text before LLM parsing
```

**`ParsedJobDescription`**
```
title: Optional[str]
company: Optional[str]
required_skills: Optional[List[str]]
preferred_skills: Optional[List[str]]
responsibilities: Optional[List[str]]
qualifications: Optional[List[str]]
salary_min: Optional[float]
salary_max: Optional[float]
salary_currency: Optional[str]
raw_text: Optional[str]
```

**`MatchResult`**
```
resume_id: str
job_description_id: str
overall_score: float          # 0-100, weighted composite
skill_match_score: float      # 0-100
experience_match_score: float # 0-100
semantic_similarity_score: float  # 0-100
matched_skills: List[str]
missing_skills: List[str]
recommendations: List[str]
# LLM sidecar fields (populated only when hybrid matching is enabled)
llm_fit_score: Optional[float]
llm_reasoning: Optional[str]
transferable_skills: List[Dict[str, str]]
experience_quality: Optional[str]
experience_quality_reasoning: Optional[str]
risk_flags: List[str]
strengths: List[str]
llm_enabled: bool             # True when LLM sidecar ran successfully
```

Core-only weights: semantic 35%, skills 40%, experience 25%.
Hybrid weights (when LLM sidecar enabled): semantic 25%, skills 30%, experience 20%, llm_fit 25%.

**`ResumeDocument`** / **`JobDescriptionDocument`** -- MongoDB wrapper models with `id`, `filename`, `file_path`, `uploaded_at`, `parsed_data`, `status`.

**`ResumeUploadResponse`** / **`JobDescriptionResponse`** / **`JobDescriptionUploadResponse`** -- API response wrappers.

**`JobDescriptionCreateRequest`** -- For creating JDs from text (not file upload): `title`, `company`, `description`, `required_skills`, `preferred_skills`, etc.

### Interview (`src/models/interview.py`)

**Enums:**
- `InterviewStatus`: `created`, `in_progress`, `paused`, `completed`, `cancelled`, `failed`
- `InterviewStage`: `screening`, `technical`, `behavioral`, `system_design`, `wrap_up`
- `InterviewMode`: `text`, `voice`, `hybrid`
- `QuestionStatus`: `pending`, `asked`, `answered`, `skipped`

**`InterviewConfig`**
```
mode: InterviewMode = "text"

# Question counts per stage
screening_questions: int = 3
technical_questions: int = 5
behavioral_questions: int = 3
system_design_questions: int = 1

# Adaptive settings
adaptive_difficulty: bool = True
enable_follow_ups: bool = True
max_follow_ups_per_question: int = 2

# Time limits (in seconds, 0 = no limit)
max_duration_seconds: int = 3600
question_timeout_seconds: int = 300

# Voice settings
tts_voice: Optional[str]
stt_model: str = "base"

# Focus areas
focus_skills: List[str]
exclude_topics: List[str]

# Question Bank settings
use_question_bank: bool = True
enabled_domains: Optional[List[str]]      # None = auto-detect
auto_detect_domains: bool = True
bank_question_ratio: float = 0.7          # 70% bank, 30% LLM-generated
allow_rephrasing: bool = True
allow_personalization: bool = True
```

**`InterviewQuestion`**
```
id: str
question_text: str
stage: InterviewStage
difficulty: str = "medium"
category: Optional[str]
purpose: str = ""
expected_answer_points: List[str]
follow_up_questions: List[str]
duration_seconds: int = 120
competency: Optional[str]         # For behavioral questions
status: QuestionStatus
source: str = "generated"         # "bank", "bank_rephrased", "bank_personalized", "generated"
audio_path: Optional[str]         # For voice mode
```

**`AnswerRecord`**
```
question_id: str
question_text: str
stage: InterviewStage
answer_text: str
answer_audio_path: Optional[str]

# Evaluation results
scores: Dict[str, float]         # e.g. {"overall": 72, "technical": 68, ...}
strengths: List[str]
improvements: List[str]
follow_up_question: Optional[str]
recommendation: str = "acceptable"

# Timing
asked_at: datetime
answered_at: Optional[datetime]
duration_seconds: Optional[float]
```

**`StageProgress`**
```
stage: InterviewStage
total_questions: int = 0
answered_questions: int = 0
average_score: float = 0.0
started_at: Optional[datetime]
completed_at: Optional[datetime]

# Computed properties:
is_complete: bool               # answered_questions >= total_questions
progress_percent: float         # 0-100
```

**`InterviewSession`**
```
id: str
resume_id: str
job_description_id: str
candidate_name: Optional[str]
role_title: Optional[str]
config: InterviewConfig
status: InterviewStatus
current_stage: InterviewStage
current_question_index: int
questions: List[InterviewQuestion]
answers: List[AnswerRecord]
stage_progress: Dict[str, StageProgress]

# Performance tracking
current_difficulty: str = "medium"
performance_trend: str = "stable"   # improving, declining, stable
strong_areas: List[str]
weak_areas: List[str]

# Timing
created_at: datetime
started_at: Optional[datetime]
completed_at: Optional[datetime]
last_activity_at: datetime

# Match analysis (computed at interview start from semantic matcher)
match_analysis: Optional[Dict[str, Any]]

# Error tracking
error_message: Optional[str]

# Computed properties:
duration_minutes: int
overall_score: float
current_question: Optional[InterviewQuestion]
```

**Request/Response models:** `StartInterviewRequest`, `StartInterviewResponse`, `SubmitAnswerRequest`, `SubmitAnswerResponse`, `InterviewProgressResponse`, `EndInterviewRequest`, `InterviewReportResponse`.

### Report (`src/models/report.py`)

**`FullInterviewReport`**
```
metadata: ReportMetadata
candidate: CandidateInfo
scores: ScoreBreakdown
questions: List[QuestionSummary]
strengths: List[ReportStrength]
concerns: List[ReportConcern]
recommendation: HiringRecommendation
executive_summary: Optional[str]
```

Has `from_orchestrator_report()` class method that converts the raw dict from `AnswerEvaluator.generate_interview_report()` into this structured model.

**`ScoreBreakdown`**
```
overall: float
sections: List[ScoreSection]    # Each has name, score, weight, details
```

Score weights: technical 40%, behavioral 25%, communication 20%, problem-solving 15%.

**`HiringRecommendation`**
```
decision: RecommendationDecision   # strong_hire, hire, maybe, no_hire, strong_no_hire
confidence: float
reasoning: str
```

**`RecommendationDecision`** enum: `strong_hire`, `hire`, `maybe`, `no_hire`, `strong_no_hire`.

**`SeverityLevel`** enum: `low`, `medium`, `high`, `critical`.

### Question Bank (`src/models/question_bank.py`)

**`QuestionCategory`** -- 17 values: `EXPLAIN`, `DESIGN`, `COMPARE`, `IMPLEMENT`, `DEBUG`, `OPTIMIZE`, `ANALYZE`, `EVALUATE`, `SCENARIO`, `BEHAVIORAL`, `SYSTEM_DESIGN`, `CODE_REVIEW`, `ARCHITECTURE`, `TESTING`, `SECURITY`, `PERFORMANCE`, `GENERAL`.

**`QuestionDifficulty`**: `EASY`, `MEDIUM`, `HARD`, `EXPERT`.

**`InterviewStageHint`**: `SCREENING`, `TECHNICAL`, `BEHAVIORAL`, `SYSTEM_DESIGN`, `GENERAL`.

**`QuestionSource`**: `BANK`, `BANK_REPHRASED`, `BANK_PERSONALIZED`, `GENERATED`.

**`BankQuestion`** -- raw from JSONL:
```
id: str
question_text: str
domain: str
difficulty: QuestionDifficulty
category: Optional[QuestionCategory]
skills: List[str]
stage_hint: InterviewStageHint = TECHNICAL
source_file: str
follow_up: Optional[str]
metadata: Optional[Dict]
```

**`EnrichedQuestion`** -- after LLM enhancement:
```
id: str
original_question: Optional[BankQuestion]    # Original bank question (if from bank)
original_text: str                            # Original question text
enhanced_text: str                            # LLM-enhanced version
domain: str
category: QuestionCategory
skills: List[str]
difficulty: QuestionDifficulty
stage_hint: InterviewStageHint
source: QuestionSource
resume_context: Optional[str]                 # What resume element it relates to
personalization_notes: Optional[str]          # Why this personalization was chosen
```

**`DOMAIN_KEYWORDS`** -- dict mapping domain names to keyword lists, used by `detect_domains_from_text()`.

### Auth (`src/models/auth.py`)

**`UserRole`** enum: `admin`, `hiring_manager`, `interviewer`, `candidate`.

**`AuthenticatedUser`**
```
user_id: str
username: str
role: UserRole
permissions: List[str]
```

**`TokenResponse`**
```
access_token: str
token_type: str = "bearer"
expires_in: int
```

## MongoDB Collections

Database name: `interview_system` (hardcoded in `src/core/database.py`).

### `resumes`
```json
{
  "_id": ObjectId,
  "filename": "resume.pdf",
  "file_path": "resumes/abc123.pdf",
  "uploaded_at": ISODate,
  "status": "parsed",
  "parsed_data": {
    "contact": { "name": "...", "email": "...", ... },
    "summary": "...",
    "skills": ["Python", "FastAPI", ...],
    "experience": [{ "title": "...", "company": "...", ... }],
    "education": [{ "degree": "...", ... }],
    "certifications": ["AWS SAA"],
    "raw_text": "full extracted text..."
  }
}
```

### `job_descriptions`
```json
{
  "_id": ObjectId,
  "title": "Senior Backend Engineer",
  "company": "Acme Corp",
  "created_at": ISODate,
  "status": "parsed",
  "parsed_data": {
    "title": "...",
    "company": "...",
    "required_skills": ["Python", "FastAPI"],
    "preferred_skills": ["Kubernetes"],
    "responsibilities": ["..."],
    "qualifications": ["..."],
    "raw_text": "..."
  }
}
```

### `interview_sessions`
```json
{
  "_id": "uuid-string",
  "resume_id": "...",
  "job_description_id": "...",
  "candidate_name": "...",
  "role_title": "...",
  "config": { ... },
  "status": "in_progress",
  "current_stage": "technical",
  "current_question_index": 3,
  "questions": [ ... ],
  "answers": [ ... ],
  "stage_progress": { ... },
  "current_difficulty": "medium",
  "performance_trend": "stable",
  "strong_areas": ["Python", "System Design"],
  "weak_areas": ["Kubernetes"],
  "match_analysis": {
    "overall_score": 68.5,
    "skill_match_score": 72.0,
    "matched_skills": ["Python", "Docker"],
    "missing_skills": ["Terraform"],
    "llm_fit_score": 65.0,
    "llm_reasoning": "...",
    "transferable_skills": [...],
    "risk_flags": [...],
    "strengths": [...],
    "llm_enabled": true
  },
  "created_at": ISODate,
  "started_at": ISODate,
  "completed_at": null,
  "last_activity_at": ISODate,
  "error_message": null
}
```

**Important:** Sessions are stored both in-memory (`InterviewOrchestrator._sessions` dict) and in MongoDB (via `SessionRepository`). During an active session, the in-memory dict is the primary source of truth, with write-through to MongoDB on every mutation. If the server restarts, `get_session()` falls back to loading from MongoDB on demand -- sessions survive restarts but are not bulk-reloaded at startup.

### `interviews` (used by `src/api/interviews.py`)
Separate from sessions. Stores interview scheduling metadata. Partially implemented -- this collection is used by a CRUD layer that appears to be legacy or parallel to the sessions system.

### `reports` (used by `src/api/interviews.py`)
Stores generated report JSON documents. The PDF binary is stored separately in the storage layer (S3 or `./storage/reports/`).

## Gotchas

1. **Enums stored as strings.** Models use `class Config: use_enum_values = True`, so MongoDB and JSON responses contain string values (`"technical"`) not enum names (`InterviewStage.TECHNICAL`).

2. **Experience dates are strings.** `Experience.start_date` and `Experience.end_date` are free-text, not parsed datetime. The semantic matcher estimates 2 years per role as a heuristic (`src/services/semantic_matcher.py`).

3. **All date fields in models are `Optional`.** Many are populated inconsistently depending on what the LLM returns during parsing.

4. **Field name normalization.** The `DocumentProcessor` handles LLM output variations: `contact`/`contact_info`/`personal_info`, `company`/`organization`/`employer`, `responsibilities`/`duties`/`key_responsibilities`, etc. See `src/services/document_processor.py` field mapping logic.

5. **`_id` vs `id`.** MongoDB uses `_id` (ObjectId). API responses convert to string `id`. The `InterviewSession.id` is a UUID string, not a MongoDB ObjectId.

6. **In-memory session state with MongoDB fallback.** `InterviewOrchestrator._sessions` is the live source of truth during an active session. Every mutation is written through to MongoDB via `SessionRepository`. On `get_session()`, if the session is not in memory (e.g., after server restart), it is loaded from MongoDB on demand. Sessions survive server restarts but are not bulk-reloaded at startup.

7. **Score validation.** `AnswerEvaluator` validates that the LLM's hiring recommendation is consistent with the calculated score. If score >= 7 but LLM says "no_hire", the evaluator overrides to prevent hallucinated decisions. See `src/services/answer_evaluator.py`.
