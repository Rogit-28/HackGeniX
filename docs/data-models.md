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
degree: Optional[str]
institution: Optional[str]
year: Optional[str]           # String, not int -- LLMs return inconsistent formats
field_of_study: Optional[str]
gpa: Optional[str]
```

**`Experience`**
```
title: Optional[str]
company: Optional[str]
duration: Optional[str]       # Free-text like "2 years" or "Jan 2020 - Mar 2022"
description: Optional[str]
technologies: Optional[List[str]]
```

**`ParsedResume`**
```
contact: Optional[ContactInfo]
summary: Optional[str]
skills: Optional[List[str]]
experience: Optional[List[Experience]]
education: Optional[List[Education]]
certifications: Optional[List[str]]
raw_text: Optional[str]       # Full extracted text before LLM parsing
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
overall_score: float
skill_match: float
experience_match: float
education_match: float
details: Optional[Dict]
```

**`ResumeDocument`** / **`JobDescriptionDocument`** -- MongoDB wrapper models with `id`, `filename`, `file_path`, `uploaded_at`, `parsed_data`, `status`.

**`ResumeUploadResponse`** / **`JobDescriptionResponse`** / **`JobDescriptionUploadResponse`** -- API response wrappers.

**`JobDescriptionCreateRequest`** -- For creating JDs from text (not file upload): `title`, `company`, `description`, `required_skills`, `preferred_skills`, etc.

### Interview (`src/models/interview.py`)

**Enums:**
- `InterviewStatus`: `pending`, `in_progress`, `paused`, `completed`, `cancelled`
- `InterviewStage`: `introduction`, `technical`, `behavioral`, `situational`, `closing`
- `InterviewMode`: `text`, `voice`, `hybrid`
- `QuestionStatus`: `pending`, `asked`, `answered`, `skipped`

**`InterviewConfig`**
```
introduction_questions: int = 2
technical_questions: int = 5
behavioral_questions: int = 3
situational_questions: int = 2
closing_questions: int = 1
adaptive_difficulty: bool = True
min_difficulty: int = 1
max_difficulty: int = 10
mode: InterviewMode = "text"
voice_settings: Optional[Dict]
use_question_bank: bool = True
bank_ratio: float = 0.7          # 70% bank, 30% LLM-generated
```

**`InterviewQuestion`**
```
id: str
question: str
stage: InterviewStage
difficulty: int
expected_topics: List[str]
status: QuestionStatus
source: Optional[str]           # "bank", "llm", "hybrid"
category: Optional[str]
skills: Optional[List[str]]
```

**`AnswerRecord`**
```
question_id: str
answer_text: str
score: Optional[float]
feedback: Optional[str]
evaluation: Optional[Dict]
answered_at: Optional[datetime]
duration_seconds: Optional[float]
```

**`StageProgress`**
```
stage: InterviewStage
total_questions: int
answered: int
average_score: Optional[float]
```

**`InterviewSession`**
```
id: str
resume_id: str
jd_id: str
config: InterviewConfig
status: InterviewStatus
current_stage: InterviewStage
current_question_index: int
questions: List[InterviewQuestion]
answers: List[AnswerRecord]
stage_progress: Dict[str, StageProgress]
match_result: Optional[MatchResult]
created_at: datetime
updated_at: Optional[datetime]
completed_at: Optional[datetime]
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

**`InterviewStageHint`**: `introduction`, `technical`, `behavioral`, `situational`, `closing`.

**`QuestionSource`**: `CURATED`, `LLM_GENERATED`, `HYBRID`.

**`BankQuestion`** -- raw from JSONL:
```
id: str
question: str
domain: str
difficulty: QuestionDifficulty
category: Optional[QuestionCategory]
skills: List[str]
expected_topics: List[str]
stage_hint: Optional[InterviewStageHint]
follow_up: Optional[str]
metadata: Optional[Dict]
```

**`EnrichedQuestion`** -- after LLM enhancement:
```
(inherits BankQuestion fields)
enhanced_question: Optional[str]
context_notes: Optional[str]
source: QuestionSource
original_id: Optional[str]
relevance_score: Optional[float]
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
  "_id": ObjectId,
  "session_id": "uuid-string",
  "resume_id": "...",
  "jd_id": "...",
  "config": { ... },
  "status": "in_progress",
  "current_stage": "technical",
  "questions": [ ... ],
  "answers": [ ... ],
  "stage_progress": { ... },
  "created_at": ISODate,
  "updated_at": ISODate
}
```

**Important:** Sessions are also stored in-memory in `InterviewOrchestrator._sessions`. The in-memory dict is the source of truth during a session. MongoDB is written to for persistence but the orchestrator reads from memory, not from the DB. If the server restarts, in-memory sessions are lost -- only MongoDB records survive, and there is no recovery mechanism to reload them.

### `interviews` (used by `src/api/interviews.py`)
Separate from sessions. Stores interview scheduling metadata. Partially implemented -- this collection is used by a CRUD layer that appears to be legacy or parallel to the sessions system.

### `reports` (used by `src/api/interviews.py`)
Stores generated report JSON documents. The PDF binary is stored separately in the storage layer (S3 or `./storage/reports/`).

## Gotchas

1. **Enums stored as strings.** Models use `class Config: use_enum_values = True`, so MongoDB and JSON responses contain string values (`"technical"`) not enum names (`InterviewStage.TECHNICAL`).

2. **Experience dates are strings.** `Experience.duration` is free-text, not parsed datetime. The semantic matcher estimates 2 years per role as a heuristic (`src/services/semantic_matcher.py`).

3. **All date fields in models are `Optional`.** Many are populated inconsistently depending on what the LLM returns during parsing.

4. **Field name normalization.** The `DocumentProcessor` handles LLM output variations: `contact`/`contact_info`/`personal_info`, `company`/`organization`/`employer`, `responsibilities`/`duties`/`key_responsibilities`, etc. See `src/services/document_processor.py` field mapping logic.

5. **`_id` vs `id`.** MongoDB uses `_id` (ObjectId). API responses convert to string `id`. The `InterviewSession.id` is a UUID string, not a MongoDB ObjectId.

6. **In-memory session state.** `InterviewOrchestrator._sessions` is the live source of truth. DB writes are fire-and-forget. No read-back from DB during active sessions.

7. **Score validation.** `AnswerEvaluator` validates that the LLM's hiring recommendation is consistent with the calculated score. If score >= 7 but LLM says "no_hire", the evaluator overrides to prevent hallucinated decisions. See `src/services/answer_evaluator.py`.
