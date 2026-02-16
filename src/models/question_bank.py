"""
Question Bank Data Models.

Models for the curated question bank system that provides base questions
for the hybrid interview question generation approach.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
import uuid


class QuestionCategory(str, Enum):
    """Categories of interview questions based on their structure/intent."""
    EXPLAIN = "explain"           # "Explain X in context of Y"
    DESIGN = "design"             # "Design a solution that uses X"
    COMPARE = "compare"           # "Compare two approaches for X"
    TROUBLESHOOT = "troubleshoot" # "Troubleshoot a failure scenario"
    PERFORMANCE = "performance"   # "What are the performance bottlenecks"
    REAL_WORLD = "real_world"     # "Give a real-world example"
    SCALE = "scale"               # "How do you scale X from 1x to 100x"
    SECURITY = "security"         # "How would you secure X"
    TESTING = "testing"           # "How would you test X"
    METRICS = "metrics"           # "Which metrics/SLIs"
    ROLLOUT = "rollout"           # "What would your rollout strategy be"
    TRADEOFFS = "tradeoffs"       # "What trade-offs would you call out"
    MENTORING = "mentoring"       # "How would you mentor a junior"
    COST = "cost"                 # "How would you reduce cost"
    TELEMETRY = "telemetry"       # "What telemetry would you add"
    WALKTHROUGH = "walkthrough"   # "Walk through a minimal baseline"
    GENERAL = "general"           # Catch-all


class QuestionDifficulty(str, Enum):
    """Difficulty levels for questions."""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class InterviewStageHint(str, Enum):
    """Hints for which interview stage a question fits."""
    SCREENING = "screening"
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    SYSTEM_DESIGN = "system_design"
    GENERAL = "general"


class QuestionSource(str, Enum):
    """Source of a question in the final interview."""
    BANK = "bank"                      # Verbatim from bank
    BANK_REPHRASED = "bank_rephrased"  # Bank question rephrased by LLM
    BANK_PERSONALIZED = "bank_personalized"  # Bank question personalized with resume
    GENERATED = "generated"            # Fully LLM-generated (gap-filling)
    FOLLOW_UP = "follow_up"            # Phase 7: Follow-up sub-question based on candidate's answer
    AUGMENTED = "augmented"            # Phase 7: Base question augmented with candidate context


class BankQuestion(BaseModel):
    """A question from the curated question bank."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    domain: str                                    # backend, aiml, system_design, etc.
    question_text: str                             # Original question text
    category: QuestionCategory = QuestionCategory.GENERAL
    skills: List[str] = Field(default_factory=list)  # Extracted skills/topics
    difficulty: QuestionDifficulty = QuestionDifficulty.MEDIUM
    stage_hint: InterviewStageHint = InterviewStageHint.TECHNICAL
    source_file: str = ""                          # File it was loaded from
    
    # Metadata for analytics
    times_used: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    def __hash__(self):
        """Hash based on question text for deduplication."""
        return hash(self.question_text.lower().strip())
    
    def __eq__(self, other):
        """Equality based on question text for deduplication."""
        if not isinstance(other, BankQuestion):
            return False
        return self.question_text.lower().strip() == other.question_text.lower().strip()


class EnrichedQuestion(BaseModel):
    """A question after LLM enhancement/personalization."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_question: Optional[BankQuestion] = None  # Original bank question (if from bank)
    original_text: str                             # Original question text
    enhanced_text: str                             # LLM-enhanced version
    domain: str
    category: QuestionCategory
    skills: List[str]
    difficulty: QuestionDifficulty
    stage_hint: InterviewStageHint
    source: QuestionSource
    
    # Personalization context
    resume_context: Optional[str] = None           # What resume element it relates to
    personalization_notes: Optional[str] = None    # Why this personalization was chosen
    
    def to_interview_question_dict(self) -> Dict[str, Any]:
        """Convert to format compatible with InterviewQuestion."""
        return {
            "question_text": self.enhanced_text,
            "stage": self.stage_hint.value,
            "difficulty": self.difficulty.value,
            "category": self.category.value,
            "purpose": f"Evaluate {', '.join(self.skills[:3])} skills",
            "expected_answer_points": [],  # Will be filled by LLM if needed
            "source": self.source.value,
        }


class DomainInfo(BaseModel):
    """Information about a loaded domain."""
    name: str
    question_count: int
    categories: Dict[str, int]         # Category -> count
    difficulties: Dict[str, int]       # Difficulty -> count
    skills: List[str]                  # All skills in this domain
    source_file: str
    loaded_at: datetime = Field(default_factory=datetime.utcnow)


class QuestionBankConfig(BaseModel):
    """Configuration for question bank usage in interviews."""
    # Enable/disable question bank
    use_question_bank: bool = True
    
    # Domain selection
    enabled_domains: Optional[List[str]] = None    # None = auto-detect from JD
    auto_detect_domains: bool = True               # Auto-detect domains from JD
    
    # Question mixing
    bank_question_ratio: float = Field(default=0.7, ge=0.0, le=1.0)  # 70% from bank
    
    # LLM enhancement options
    allow_rephrasing: bool = True                  # LLM can rephrase for natural flow
    allow_personalization: bool = True             # LLM can add resume context
    
    # Filtering
    difficulty_filter: Optional[QuestionDifficulty] = None  # Only questions of this difficulty
    exclude_categories: List[QuestionCategory] = Field(default_factory=list)
    include_categories: Optional[List[QuestionCategory]] = None  # If set, only these categories
    
    # Diversity settings
    max_questions_per_category: int = 3            # Avoid too many of same type
    ensure_category_variety: bool = True           # Try to include different categories


class QuestionBankStats(BaseModel):
    """Statistics about the question bank."""
    total_questions: int
    loaded_domains: List[str]
    available_domains: List[str]
    questions_by_domain: Dict[str, int]
    questions_by_category: Dict[str, int]
    questions_by_difficulty: Dict[str, int]
    unique_skills: List[str]


# Domain name mappings for auto-detection
DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "backend": [
        "backend", "api", "rest", "graphql", "grpc", "microservices",
        "database", "sql", "nosql", "redis", "caching", "queue",
        "kafka", "rabbitmq", "server", "python", "java", "go", "node",
        "fastapi", "django", "flask", "spring", "express",
    ],
    "system_design": [
        "system design", "architecture", "scalability", "distributed",
        "high availability", "load balancing", "sharding", "replication",
        "consistency", "cap theorem", "microservices architecture",
    ],
    "aiml": [
        "machine learning", "ml", "ai", "artificial intelligence",
        "deep learning", "neural network", "nlp", "computer vision",
        "tensorflow", "pytorch", "transformers", "llm", "gpt",
        "rag", "embeddings", "fine-tuning", "training",
    ],
    "devops_sre": [
        "devops", "sre", "kubernetes", "k8s", "docker", "container",
        "ci/cd", "jenkins", "github actions", "terraform", "ansible",
        "monitoring", "prometheus", "grafana", "observability",
        "incident", "on-call", "slo", "sli", "sla",
    ],
    "data_engineering": [
        "data engineering", "etl", "data pipeline", "spark", "airflow",
        "data warehouse", "snowflake", "bigquery", "redshift",
        "streaming", "batch processing", "data lake",
    ],
    "security": [
        "security", "authentication", "authorization", "oauth", "jwt",
        "encryption", "cryptography", "owasp", "vulnerability",
        "penetration testing", "security audit", "compliance",
    ],
    "web_dev": [
        "frontend", "react", "vue", "angular", "javascript", "typescript",
        "css", "html", "web", "browser", "dom", "spa", "ssr",
        "webpack", "vite", "nextjs", "responsive",
    ],
    "mobile": [
        "mobile", "ios", "android", "swift", "kotlin", "react native",
        "flutter", "mobile app", "app store", "push notification",
    ],
    "ml_ops": [
        "mlops", "ml ops", "model deployment", "model serving",
        "feature store", "experiment tracking", "mlflow", "kubeflow",
        "model monitoring", "a/b testing models",
    ],
    "software_engineer": [
        "software engineering", "coding", "algorithms", "data structures",
        "oop", "design patterns", "solid", "testing", "debugging",
        "code review", "refactoring", "clean code",
    ],
}


def detect_domains_from_text(text: str, top_n: int = 3) -> List[str]:
    """
    Detect relevant domains from text (JD or resume).
    
    Args:
        text: Text to analyze
        top_n: Maximum number of domains to return
        
    Returns:
        List of domain names, ordered by relevance
    """
    text_lower = text.lower()
    domain_scores: Dict[str, int] = {}
    
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword in text_lower:
                # Longer keywords get higher weight
                score += len(keyword.split())
        if score > 0:
            domain_scores[domain] = score
    
    # Sort by score descending
    sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
    
    return [domain for domain, _ in sorted_domains[:top_n]]
