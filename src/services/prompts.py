"""
Interview Question Prompts and Templates.

Contains structured prompts for generating interview questions,
evaluating answers, and conducting different interview stages.
"""
from typing import List, Dict, Any
from dataclasses import dataclass
from enum import Enum


class InterviewStage(str, Enum):
    """Interview stages."""
    SCREENING = "screening"
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    SYSTEM_DESIGN = "system_design"
    WRAP_UP = "wrap_up"


class QuestionDifficulty(str, Enum):
    """Question difficulty levels."""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass
class QuestionTemplate:
    """Template for generating questions."""
    stage: InterviewStage
    difficulty: QuestionDifficulty
    prompt: str
    follow_up_prompt: str
    expected_duration_seconds: int = 120


# System prompts for the AI interviewer
INTERVIEWER_SYSTEM_PROMPT = """You are an expert technical interviewer for a software engineering position. 
Your role is to:
1. Generate relevant, insightful interview questions based on the job description and candidate's resume
2. Assess candidate responses fairly and objectively
3. Ask appropriate follow-up questions to probe deeper understanding
4. Maintain a professional but friendly tone throughout

Key guidelines:
- Questions should be specific to the role requirements
- Tailor difficulty based on the candidate's experience level
- Focus on practical, real-world scenarios
- Avoid trick questions or gotchas
- Be encouraging while maintaining rigor"""


# Question generation prompts
QUESTION_GENERATION_PROMPTS = {
    InterviewStage.SCREENING: """Generate {num_questions} screening questions for a {role_title} position.

Job Description Summary:
{jd_summary}

Candidate Background:
{resume_summary}

Requirements:
- Questions should verify basic qualifications
- Include at least one question about career motivation
- Keep questions concise (answerable in 1-2 minutes)
- Difficulty: Easy to Medium

Output format (JSON array):
[
  {{
    "question": "The question text",
    "purpose": "What this question assesses",
    "expected_answer_points": ["key point 1", "key point 2"],
    "difficulty": "easy|medium",
    "duration_seconds": 60
  }}
]""",

    InterviewStage.TECHNICAL: """Generate {num_questions} technical interview questions for a {role_title} position.

Required Skills:
{required_skills}

Candidate's Technical Background:
{technical_background}

Focus Areas:
{focus_areas}

Requirements:
- Questions should test practical knowledge, not memorization
- Include coding/problem-solving scenarios where appropriate
- Mix of conceptual and hands-on questions
- Progressive difficulty (start medium, can go to hard)

Output format (JSON array):
[
  {{
    "question": "The question text",
    "category": "algorithms|system-design|language-specific|domain-knowledge",
    "purpose": "What this question assesses",
    "expected_answer_points": ["key point 1", "key point 2", "key point 3"],
    "follow_up_questions": ["follow-up 1", "follow-up 2"],
    "difficulty": "medium|hard",
    "duration_seconds": 180
  }}
]""",

    InterviewStage.BEHAVIORAL: """Generate {num_questions} behavioral interview questions for a {role_title} position.

Job Requirements:
{jd_summary}

Candidate Experience:
{experience_summary}

Key Competencies to Assess:
{competencies}

Requirements:
- Use STAR format prompts (Situation, Task, Action, Result)
- Focus on past experiences that predict future performance
- Include questions about teamwork, challenges, and growth
- Assess cultural fit and soft skills

Output format (JSON array):
[
  {{
    "question": "The question text (STAR format)",
    "competency": "leadership|teamwork|problem-solving|communication|adaptability",
    "purpose": "What this question assesses",
    "red_flags": ["warning sign 1", "warning sign 2"],
    "green_flags": ["positive indicator 1", "positive indicator 2"],
    "difficulty": "medium",
    "duration_seconds": 180
  }}
]""",

    InterviewStage.SYSTEM_DESIGN: """Generate {num_questions} system design questions for a {role_title} position.

Technical Requirements:
{technical_requirements}

Candidate's System Experience:
{system_experience}

Scale/Complexity Level:
{complexity_level}

Requirements:
- Questions should be open-ended design problems
- Include scalability considerations
- Appropriate for candidate's experience level
- Focus on practical, real-world systems

Output format (JSON array):
[
  {{
    "question": "Design a system that...",
    "category": "distributed-systems|data-intensive|real-time|microservices",
    "key_components": ["component 1", "component 2"],
    "expected_discussion_points": ["scalability", "reliability", "trade-offs"],
    "follow_up_questions": ["What if we need to handle 10x traffic?"],
    "difficulty": "hard",
    "duration_seconds": 300
  }}
]""",
}


# Answer evaluation prompts
ANSWER_EVALUATION_PROMPT = """Evaluate the candidate's answer to an interview question.

Question: {question}

Expected Answer Points:
{expected_points}

Candidate's Answer:
{answer}

Evaluate on these criteria:
1. Technical Accuracy (0-100): Is the answer factually correct?
2. Completeness (0-100): Did they address all key points?
3. Clarity (0-100): Was the explanation clear and well-structured?
4. Depth (0-100): Did they demonstrate deep understanding?

Also provide:
- Key strengths in the answer
- Areas for improvement
- Suggested follow-up question (if needed)
- Overall recommendation

Output format (JSON):
{{
  "scores": {{
    "technical_accuracy": 0-100,
    "completeness": 0-100,
    "clarity": 0-100,
    "depth": 0-100,
    "overall": 0-100
  }},
  "strengths": ["strength 1", "strength 2"],
  "improvements": ["area 1", "area 2"],
  "follow_up_question": "optional follow-up or null",
  "recommendation": "strong|acceptable|weak|insufficient",
  "notes": "Brief evaluation summary"
}}"""


BEHAVIORAL_EVALUATION_PROMPT = """Evaluate the candidate's behavioral answer using STAR criteria.

Question: {question}
Competency Being Assessed: {competency}

Candidate's Answer:
{answer}

STAR Evaluation:
1. Situation (0-25): Did they clearly describe the context?
2. Task (0-25): Did they explain their specific responsibility?
3. Action (0-25): Did they describe concrete actions they took?
4. Result (0-25): Did they share measurable outcomes?

Also assess:
- Authenticity: Does this seem like a genuine experience?
- Relevance: Is this example relevant to the role?
- Self-awareness: Did they show reflection and learning?

Red flags to watch for:
{red_flags}

Green flags (positive indicators):
{green_flags}

Output format (JSON):
{{
  "star_scores": {{
    "situation": 0-25,
    "task": 0-25,
    "action": 0-25,
    "result": 0-25,
    "total": 0-100
  }},
  "authenticity_score": 0-100,
  "relevance_score": 0-100,
  "self_awareness_score": 0-100,
  "overall_score": 0-100,
  "red_flags_detected": ["flag if any"],
  "green_flags_detected": ["flag if any"],
  "recommendation": "strong|acceptable|weak|concerning",
  "notes": "Brief evaluation summary"
}}"""


# Follow-up question generation
FOLLOW_UP_PROMPT = """Based on the candidate's answer, generate an appropriate follow-up question.

Original Question: {original_question}

Candidate's Answer:
{answer}

Evaluation Summary:
{evaluation_summary}

Guidelines:
- If answer was incomplete, probe for missing details
- If answer was vague, ask for specific examples
- If answer showed expertise, dig deeper into advanced topics
- If answer revealed potential weakness, explore tactfully

Generate ONE follow-up question that will best assess the candidate's true capabilities.

Output format (JSON):
{{
  "follow_up_question": "The question text",
  "purpose": "Why this follow-up is valuable",
  "expected_depth": "What a good answer would include"
}}"""


# Adaptive difficulty prompts
DIFFICULTY_ADJUSTMENT_PROMPT = """Based on the candidate's performance so far, determine the appropriate difficulty for the next question.

Performance Summary:
- Questions answered: {questions_answered}
- Average score: {average_score}
- Trend: {trend}  (improving/declining/stable)
- Strongest areas: {strong_areas}
- Weakest areas: {weak_areas}

Current difficulty level: {current_difficulty}

Determine:
1. Should difficulty increase, decrease, or stay the same?
2. Which topic areas need more probing?
3. Any areas to skip (already demonstrated mastery)?

Output format (JSON):
{{
  "next_difficulty": "easy|medium|hard",
  "difficulty_change": "increase|decrease|maintain",
  "reason": "Brief explanation",
  "focus_areas": ["area to probe more"],
  "skip_areas": ["area already demonstrated"],
  "candidate_trajectory": "strong|on-track|struggling"
}}"""


# Report generation prompts
INTERVIEW_SUMMARY_PROMPT = """Generate a comprehensive interview summary and hiring recommendation.

Position: {role_title}
Candidate: {candidate_name}
Interview Duration: {duration_minutes} minutes

Performance by Stage:
{stage_performances}

Question-by-Question Breakdown:
{question_breakdown}

Scoring Summary:
- Technical Skills: {technical_score}/100
- Behavioral/Soft Skills: {behavioral_score}/100
- Communication: {communication_score}/100
- Problem Solving: {problem_solving_score}/100
- Cultural Fit: {cultural_fit_score}/100
- Overall: {overall_score}/100

Generate:
1. Executive Summary (2-3 sentences)
2. Key Strengths (top 3-5)
3. Areas of Concern (if any)
4. Hiring Recommendation with confidence level
5. Suggested next steps

Output format (JSON):
{{
  "executive_summary": "Brief overall assessment",
  "strengths": [
    {{"area": "strength area", "evidence": "specific example from interview"}}
  ],
  "concerns": [
    {{"area": "concern area", "severity": "minor|moderate|major", "evidence": "specific example"}}
  ],
  "recommendation": "strong_hire|hire|no_hire|strong_no_hire",
  "confidence": 0-100,
  "reasoning": "Detailed justification for recommendation",
  "next_steps": ["suggested action 1", "suggested action 2"],
  "comparison_notes": "How candidate compares to typical candidates for this role"
}}"""


# ============================================================================
# Question Bank Enhancement Prompts (Phase 6.5 - Hybrid Question Generation)
# ============================================================================

ENHANCE_BANK_QUESTION_PROMPT = """You are an expert technical interviewer. Your task is to rephrase and personalize an interview question from our question bank.

**Original Bank Question:**
{bank_question}

**Domain:** {domain}
**Question Category:** {category}
**Target Difficulty:** {difficulty}

**Candidate Resume Summary:**
{resume_summary}

**Candidate's Relevant Experience:**
{relevant_experience}

**Job Description Requirements:**
{jd_requirements}

**Your task:**
1. Rephrase the question to sound natural and conversational
2. If the candidate has relevant experience, personalize the question to reference it
3. Maintain the core intent, difficulty, and scope of the original question
4. Keep the question concise but complete

**Guidelines:**
- Do NOT change the fundamental topic or make it easier/harder
- If personalizing, do it subtly (e.g., "Given your experience at [company]..." or "You mentioned working with [technology]...")
- If no relevant experience matches, just rephrase for natural flow without personalization
- Output ONLY the rephrased question, nothing else

**Rephrased Question:**"""


PERSONALIZE_BANK_QUESTION_PROMPT = """Personalize this interview question based on the candidate's background.

**Original Question:**
{bank_question}

**Candidate's Background:**
- Name: {candidate_name}
- Current/Recent Role: {current_role}
- Key Skills: {skills}
- Notable Experience: {notable_experience}

**Personalization Approach:**
- Reference a specific technology or project from their resume if relevant
- Frame the question in context of their industry experience
- Make it feel like a natural conversation, not a generic interview

**Output the personalized question only:**"""


GAP_FILLING_QUESTION_PROMPT = """Generate interview questions for skills that are NOT covered by our curated question bank.

**Uncovered Skills (generate questions for these):**
{uncovered_skills}

**Interview Stage:** {stage}
**Target Difficulty:** {difficulty}
**Number of Questions to Generate:** {count}

**Candidate Background:**
{resume_summary}

**Job Description Requirements:**
{jd_requirements}

**Example questions from our bank (match this style and depth):**
{example_questions}

**Guidelines:**
1. Generate questions that specifically test the uncovered skills
2. Match the difficulty level and depth of the example questions
3. Questions should be practical and scenario-based, not trivia
4. Consider the candidate's experience level when framing questions
5. Each question should be answerable in 2-3 minutes

**Output format (JSON array):**
[
  {{
    "question": "The question text",
    "skill": "Primary skill being tested",
    "category": "explain|design|troubleshoot|compare|scale|security|testing|general",
    "purpose": "What this question assesses",
    "expected_answer_points": ["key point 1", "key point 2"],
    "difficulty": "{difficulty}",
    "duration_seconds": 120
  }}
]"""


BATCH_ENHANCE_QUESTIONS_PROMPT = """Rephrase and enhance these interview questions from our question bank.

**Questions to Enhance:**
{questions_json}

**Candidate Context:**
- Role Applied: {role_title}
- Experience Level: {experience_level}
- Key Skills: {candidate_skills}
- Notable Background: {background_summary}

**Instructions:**
1. Rephrase each question to sound natural and conversational
2. Add subtle personalization where the candidate's experience is relevant
3. Maintain original difficulty and intent
4. Return questions in the same order

**Output format (JSON array with same length as input):**
[
  {{
    "original_id": "id from input",
    "enhanced_question": "The rephrased/personalized question",
    "personalization_applied": true|false,
    "personalization_reason": "Why/how personalized, or null if not applicable"
  }}
]"""


DOMAIN_DETECTION_PROMPT = """Analyze this job description and determine the most relevant technical domains for interview questions.

**Job Title:** {job_title}

**Job Description:**
{jd_text}

**Required Skills:**
{required_skills}

**Preferred Skills:**
{preferred_skills}

**Available Domains:**
{available_domains}

**Task:**
Rank the top 3 most relevant domains for this position, with confidence scores.

**Output format (JSON):**
{{
  "primary_domain": "most relevant domain",
  "secondary_domains": ["second", "third"],
  "domain_scores": {{
    "domain_name": 0-100 confidence score
  }},
  "reasoning": "Brief explanation of domain selection"
}}"""


# ============================================================================
# End Question Bank Enhancement Prompts
# ============================================================================


# Hallucination detection prompt
HALLUCINATION_CHECK_PROMPT = """Verify that the evaluation is grounded in the candidate's actual response.

Original Question: {question}

Candidate's Answer:
{answer}

Generated Evaluation:
{evaluation}

Check for:
1. Does the evaluation only reference things actually said by the candidate?
2. Are the scores justified by specific parts of the answer?
3. Are there any assumptions or inferences not supported by the text?

Output format (JSON):
{{
  "is_grounded": true|false,
  "issues": [
    {{"type": "unsupported_claim|score_not_justified|missing_evidence", "description": "..."}}
  ],
  "confidence": 0-100,
  "corrected_evaluation": null or corrected JSON if issues found
}}"""


# ============================================================================
# LLM-Based Document Extraction Prompts
# ============================================================================

RESUME_EXTRACTION_PROMPT = """Extract structured information from this resume text.

**Resume Text:**
{resume_text}

**Instructions:**
Parse the resume and extract all information into the JSON structure below.
Be thorough - extract ALL experience entries, ALL skills, ALL education.
The candidate's name is typically at the very top of the resume.

**Output JSON format:**
{{
    "contact": {{
        "full_name": "Candidate's full name (First Last)",
        "email": "email@example.com or null",
        "phone": "phone number as shown or null",
        "linkedin": "LinkedIn URL or username or null",
        "github": "GitHub URL or username or null",
        "location": "City, State/Country or null"
    }},
    "summary": "Professional summary or objective statement (null if not present)",
    "skills": ["skill1", "skill2", "skill3"],
    "experience": [
        {{
            "company": "Company Name",
            "title": "Job Title",
            "location": "City, Country or null",
            "start_date": "Start date as shown (e.g., Jan 2020, 2020-01, 2020)",
            "end_date": "End date or Present or null",
            "description": "Role description or responsibilities",
            "highlights": ["key achievement 1", "key achievement 2"]
        }}
    ],
    "education": [
        {{
            "institution": "University/School Name",
            "degree": "Degree type (B.S., M.S., PhD, etc.)",
            "field": "Field of study or major",
            "start_date": "Start year or null",
            "end_date": "End/graduation year",
            "gpa": null or numeric GPA if mentioned
        }}
    ],
    "certifications": ["Certification 1", "Certification 2"],
    "projects": [
        {{
            "name": "Project Name",
            "description": "Brief description",
            "technologies": ["tech1", "tech2"],
            "url": "project URL if mentioned or null"
        }}
    ],
    "extraction_confidence": {{
        "name": 0.0-1.0,
        "contact": 0.0-1.0,
        "experience": 0.0-1.0,
        "skills": 0.0-1.0,
        "education": 0.0-1.0
    }}
}}

**Rules:**
- Use null for missing/uncertain fields, never empty strings
- Extract ALL entries from each section, not just the first few
- Skills should include: programming languages, frameworks, databases, tools, cloud platforms, methodologies
- For dates, preserve the original format from the resume
- Be precise with the candidate's full name - it's usually the largest text at the top
- Do not confuse university names, company names, or location names with the candidate's name
- If GPA is mentioned as percentage, convert to 4.0 scale (divide by 25)

**Return ONLY the JSON object, no markdown, no explanation.**"""


JD_EXTRACTION_PROMPT = """Extract structured information from this job description.

**Job Description Text:**
{jd_text}

**Output JSON format:**
{{
    "title": "Job title/position",
    "company": "Company name or null",
    "location": "Location or Remote or null",
    "employment_type": "full-time, part-time, contract, or null",
    "experience_level": "entry, junior, mid, senior, lead, principal, or null",
    "experience_years_min": minimum years required as integer or null,
    "experience_years_max": maximum years as integer or null,
    "salary_min": minimum salary as number or null,
    "salary_max": maximum salary as number or null,
    "salary_currency": "USD, INR, EUR, etc. or null",
    "required_skills": ["must-have skill 1", "must-have skill 2"],
    "preferred_skills": ["nice-to-have skill 1", "nice-to-have skill 2"],
    "responsibilities": [
        "Key responsibility 1",
        "Key responsibility 2"
    ],
    "qualifications": [
        "Required qualification 1",
        "Required qualification 2"
    ],
    "benefits": ["benefit 1", "benefit 2"],
    "team_info": "Information about the team or null",
    "extraction_confidence": {{
        "title": 0.0-1.0,
        "skills": 0.0-1.0,
        "requirements": 0.0-1.0
    }}
}}

**Rules:**
- Distinguish between REQUIRED skills (must-have) and PREFERRED skills (nice-to-have)
- Extract specific technology names, not generic terms
- For experience level, infer from context if not explicitly stated
- Include both technical and soft skill requirements
- Responsibilities should be action-oriented statements

**Return ONLY the JSON object, no markdown, no explanation.**"""


# Prompt for candidate-JD fit analysis
CANDIDATE_FIT_ANALYSIS_PROMPT = """Analyze the candidate's fit for this role based on their resume and the job requirements.

**Candidate Resume Summary:**
{resume_summary}

**Job Requirements:**
{jd_summary}

**Match Scores (computed):**
- Overall Score: {overall_score}/100
- Skill Match: {skill_score}/100
- Experience Match: {experience_score}/100

**Matched Skills:** {matched_skills}
**Missing Skills:** {missing_skills}

**Provide analysis in this JSON format:**
{{
    "overall_fit": "strong|moderate|weak",
    "fit_score": 0-100,
    "strengths": [
        "Specific strength relevant to this role"
    ],
    "concerns": [
        "Specific concern or gap"
    ],
    "interview_focus_areas": [
        "Topic to probe during interview"
    ],
    "summary": "2-3 sentence executive summary of candidate fit",
    "recommendation": "proceed|conditional|reject",
    "recommendation_reasoning": "Brief explanation of recommendation"
}}

**Be specific and actionable. Reference actual skills and experience from the resume.**"""
