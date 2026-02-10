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

{match_context}

Requirements:
- Questions should verify basic qualifications
- Include at least one question about career motivation
- Keep questions concise (answerable in 1-2 minutes)
- Difficulty: Easy to Medium
- If match analysis is provided: reference specific matched skills to confirm depth, ask about missing skills to gauge willingness to learn, and probe any risk flags with open-ended questions

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

{match_context}

Requirements:
- Questions should test practical knowledge, not memorization
- Include coding/problem-solving scenarios where appropriate
- Mix of conceptual and hands-on questions
- Progressive difficulty (start medium, can go to hard)
- If match analysis is provided: probe matched skills for real depth (not just keyword familiarity), test missing skills that are critical to the role, explore transferable skills by asking how existing knowledge applies, and directly investigate risk flags with concrete technical scenarios. Reference the candidate's actual projects by name when possible.

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

{match_context}

Requirements:
- Use STAR format prompts (Situation, Task, Action, Result)
- Focus on past experiences that predict future performance
- Include questions about teamwork, challenges, and growth
- Assess cultural fit and soft skills
- If match analysis is provided: use strengths to craft questions that let the candidate showcase proven areas, use risk flags to probe for behavioral evidence (e.g., if a risk flag mentions "no production exposure," ask about handling production incidents or ambiguity), and reference experience quality to calibrate question complexity.

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

{match_context}

Requirements:
- Questions should be open-ended design problems
- Include scalability considerations
- Appropriate for candidate's experience level
- Focus on practical, real-world systems
- If match analysis is provided: design the problem around the candidate's matched skills so they can demonstrate expertise, incorporate missing skills as natural extension points (e.g., "how would you add caching?" if caching is missing), and use transferable skills to create bridging scenarios. Calibrate complexity based on experience quality.

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
ANSWER_EVALUATION_PROMPT = """You are a strict technical interview evaluator. Your job is to catch wrong, vague, and BS answers — not to find reasons to be generous.

**STEP 1 — Generate the correct answer rubric.**
Before looking at the candidate's answer, write down what a CORRECT and COMPLETE answer to this question must include. List 4-6 specific technical points that a competent engineer would cover. These are the facts you will judge against.

**Question:** {question}

**Pre-supplied expected points (may be empty — if so, you MUST generate your own):**
{expected_points}

**STEP 2 — Read the candidate's answer and score it against your rubric.**

**Candidate's Answer:**
{answer}

**Scoring criteria with calibration anchors:**

1. **Technical Accuracy (0-100):** Is the answer factually correct?
   - 0-15: Answer is factually wrong, contains misconceptions, or is completely irrelevant to the question
   - 16-35: Answer contains some correct elements but has significant errors or confuses key concepts
   - 36-55: Answer is partially correct but has notable inaccuracies or misunderstandings
   - 56-75: Answer is mostly correct with minor inaccuracies
   - 76-90: Answer is technically accurate with no meaningful errors
   - 91-100: Answer is flawless and demonstrates expert-level precision

2. **Completeness (0-100):** How many of the rubric points did the candidate address?
   - 0-15: Addressed none or almost none of the expected points
   - 16-35: Addressed roughly 1 out of 5 expected points
   - 36-55: Addressed about half the expected points
   - 56-75: Addressed most expected points but missed important ones
   - 76-90: Addressed nearly all expected points
   - 91-100: Addressed all expected points and added valuable extras

3. **Clarity (0-100):** Was the explanation clear, structured, and easy to follow?
   - 0-15: Incoherent, rambling, or impossible to follow
   - 16-35: Poorly structured, hard to follow the reasoning
   - 36-55: Understandable but disorganized or unnecessarily verbose
   - 56-75: Reasonably clear with minor structural issues
   - 76-90: Well-structured and easy to follow
   - 91-100: Exceptionally clear, concise, and well-organized

4. **Depth (0-100):** Did they demonstrate genuine understanding beyond surface-level?
   - 0-15: No understanding demonstrated; answer is superficial buzzwords or hand-waving
   - 16-35: Surface-level only; could have been memorized without understanding
   - 36-55: Some understanding but lacks nuance or practical insight
   - 56-75: Good understanding with some practical awareness
   - 76-90: Deep understanding with trade-off awareness and practical experience
   - 91-100: Expert-level depth with novel insights

**CRITICAL RULES:**
- An answer that is confident but WRONG scores 0-15 on technical_accuracy. Confidence is not correctness.
- An answer that is vague, generic, or could apply to any question scores 0-35 on completeness and depth.
- An answer that merely restates the question or uses buzzwords without substance scores 0-25 overall.
- Do NOT award points for communication style, enthusiasm, or confidence when the technical content is wrong.
- The overall score must be a WEIGHTED RESULT: technical_accuracy * 0.35 + completeness * 0.25 + clarity * 0.20 + depth * 0.20. Compute it; do not estimate.
- If you cannot identify at least 2 specific correct technical claims in the answer, overall must be below 40.

**Output format (JSON):**
{{
  "rubric_points": ["point 1 a correct answer must cover", "point 2", "point 3", "point 4"],
  "rubric_matches": ["which rubric points the candidate actually addressed correctly"],
  "rubric_misses": ["which rubric points the candidate missed or got wrong"],
  "scores": {{
    "technical_accuracy": 0-100,
    "completeness": 0-100,
    "clarity": 0-100,
    "depth": 0-100,
    "overall": 0-100
  }},
  "strengths": ["specific strength with evidence from the answer"],
  "improvements": ["specific gap or error with what the correct answer should include"],
  "follow_up_question": "a probing question to test deeper or clarify a weakness, or null",
  "recommendation": "strong|acceptable|weak|insufficient",
  "notes": "1-2 sentence summary justifying the overall score"
}}"""


BEHAVIORAL_EVALUATION_PROMPT = """You are a strict behavioral interview evaluator. Your job is to distinguish genuine, substantive experiences from vague, fabricated, or rehearsed non-answers.

**STEP 1 — Establish what a good answer looks like.**
Before reading the candidate's answer, consider: for this competency and question, what would a genuine, high-quality STAR response include? Write down 3-4 specific indicators of authenticity and substance.

**Question:** {question}
**Competency Being Assessed:** {competency}

**Pre-supplied red flags to watch for (may be empty — if so, generate your own):**
{red_flags}

**Pre-supplied green flags / positive indicators (may be empty — if so, generate your own):**
{green_flags}

**STEP 2 — Read the candidate's answer and evaluate it.**

**Candidate's Answer:**
{answer}

**STAR Evaluation with calibration anchors:**

1. **Situation (0-25):** Did they clearly describe a specific, real context?
   - 0-5: No situation described, or generic/hypothetical ("I would...")
   - 6-12: Vague situation without specifics (no team size, company, timeline)
   - 13-18: Reasonable situation but missing key context details
   - 19-25: Specific, detailed, believable situation with concrete context

2. **Task (0-25):** Did they explain their specific responsibility?
   - 0-5: No task described, or task is indistinguishable from the situation
   - 6-12: Vague responsibility ("I helped with the project")
   - 13-18: Clear task but unclear why it was their specific responsibility
   - 19-25: Clear, specific ownership of a well-defined task

3. **Action (0-25):** Did they describe concrete actions THEY took (not the team)?
   - 0-5: No actions described, or only describes what the team did
   - 6-12: Generic actions without specifics ("I communicated with stakeholders")
   - 13-18: Some specific actions but missing detail on HOW they did it
   - 19-25: Detailed, specific actions clearly attributable to the candidate

4. **Result (0-25):** Did they share measurable outcomes?
   - 0-5: No result mentioned, or result is vague ("it went well")
   - 6-12: Qualitative result only, no metrics or concrete outcomes
   - 13-18: Some measurable outcome but unclear if it was caused by their actions
   - 19-25: Specific, quantified results clearly linked to their actions

**Additional assessment:**
- **Authenticity (0-100):** Does this sound like a real experience or a rehearsed/fabricated story?
  - 0-25: Clearly generic, hypothetical, or fabricated (no specifics, uses "would" instead of "did")
  - 26-50: Could be real but lacks the messy details that real experiences have
  - 51-75: Likely real, has some specific details but could be embellished
  - 76-100: Clearly genuine — includes specific names, numbers, challenges, and honest reflection

- **Relevance (0-100):** Is this example relevant to the competency being assessed?
  - 0-25: Completely irrelevant to the competency
  - 26-50: Tangentially related but doesn't demonstrate the competency
  - 51-75: Related but only partially demonstrates the competency
  - 76-100: Directly demonstrates the competency being assessed

- **Self-awareness (0-100):** Did they show reflection, learning, or honest acknowledgment of challenges?
  - 0-25: No reflection; presented everything as perfect
  - 26-50: Minimal reflection; formulaic "I learned..." without substance
  - 51-75: Some genuine reflection but surface-level
  - 76-100: Thoughtful reflection showing real learning and growth

**CRITICAL RULES:**
- An answer that uses "I would..." instead of "I did..." is hypothetical, NOT behavioral. Score Situation and Action at 0-5.
- An answer that only describes what the team did without clarifying the candidate's individual contribution scores 0-12 on Action.
- Vague answers without specific details (names, numbers, timelines, technologies) score below 50 on authenticity.
- If the answer does not follow STAR structure at all, the total STAR score must be below 30.
- overall_score must reflect: (star_total * 0.40) + (authenticity * 0.25) + (relevance * 0.20) + (self_awareness * 0.15). Compute it; do not estimate.

**Output format (JSON):**
{{
  "quality_indicators": ["3-4 things a good answer to this question should include"],
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
  "red_flags_detected": ["specific red flag observed with evidence from the answer"],
  "green_flags_detected": ["specific green flag observed with evidence from the answer"],
  "recommendation": "strong|acceptable|weak|concerning",
  "notes": "1-2 sentence summary justifying the overall score"
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

RESUME_EXTRACTION_PROMPT = """You are a JSON formatter. Your ONLY job is to map the raw resume text below into structured key-value pairs. You must copy every word VERBATIM from the resume — do NOT summarize, rephrase, shorten, paraphrase, or omit any text.

**Raw Resume Text:**
{resume_text}

**Your task:**
Read every line of the text above. For each piece of information, decide which JSON key it belongs to and copy it there word-for-word. Generate key-value pairs that capture EVERYTHING in the resume.

**RULES (read before you start):**
1. COPY VERBATIM — every bullet point, description, highlight must be copied exactly as written. Preserve every number, metric, percentage, and technical term.
2. SKILLS — scan the ENTIRE resume and collect every technology, tool, language, framework, library, platform, database, cloud service, API, and methodology mentioned anywhere: skills sections, project parentheticals, experience bullets, research descriptions. Flatten all sub-categories into one flat list.
3. PER-ENTRY SKILLS — for each experience, project, and research entry, also list the specific skills/technologies mentioned in THAT entry's text.
4. IMPACT — for each experience, project, and research entry, extract every quantified metric, number, or measurable outcome (e.g. "700+ partners", "94% accuracy", "16-18 hours saved", "SSIM of 0.742").
5. PROJECTS — technologies listed in parentheses next to a project name are the tech_stack. Skills includes tech_stack PLUS any additional technologies mentioned in the bullet points (e.g. if "Streamlit" appears in a bullet but not the parenthetical, it goes in skills but not tech_stack).
6. DYNAMIC SECTIONS — if the resume has sections not covered by the schema below (e.g. Awards, Volunteer Work, Publications, Hobbies, Languages), add them under "extra_sections" as key-value pairs.
7. Use null for missing/uncertain fields, never empty strings.
8. The candidate's name is the largest text at the very top. Do NOT confuse it with university, company, or location names.
9. Preserve original date formats from the resume.
10. If GPA is a percentage, convert to 4.0 scale (divide by 25).

**Output JSON structure:**
{{
    "contact": {{
        "name": "Full name from top of resume",
        "email": "email or null",
        "phone": "phone exactly as shown or null",
        "linkedin": "LinkedIn URL/username or null",
        "github": "GitHub URL/username or null",
        "location": "location or null"
    }},
    "summary": "Professional summary copied verbatim, or null if not present",
    "education": [
        {{
            "institution": "University name",
            "degree": "Degree type (B.Tech, M.S., etc.)",
            "field": "Field of study",
            "start_date": "start or null",
            "end_date": "end or Expected year",
            "gpa": 0.0
        }}
    ],
    "experience": [
        {{
            "company": "Company name",
            "title": "Job title / role",
            "location": "City or null",
            "start_date": "start date as shown",
            "end_date": "end date or Present or null",
            "highlights": [
                "Copy each bullet point EXACTLY as written in the resume"
            ],
            "skills": ["every technology/tool mentioned in THIS entry's bullets"],
            "impact": ["every quantified metric from THIS entry, e.g. 700+ partners, 15+ APIs"]
        }}
    ],
    "projects": [
        {{
            "name": "Project name (without parenthetical tech list)",
            "tech_stack": ["technologies listed in parentheses next to project name"],
            "highlights": [
                "Copy each bullet point EXACTLY as written"
            ],
            "skills": ["tech_stack items PLUS any additional technologies from the bullets"],
            "impact": ["every quantified metric, e.g. 94% accuracy, 65ms latency"]
        }}
    ],
    "research": [
        {{
            "title": "Research title verbatim",
            "venue": "Publication venue or null",
            "status": "Published, Awaiting Approval, etc. or null",
            "highlights": [
                "Copy each bullet point EXACTLY as written"
            ],
            "skills": ["technologies/methods mentioned"],
            "impact": ["quantified results, e.g. SSIM of 0.742, PSNR of 23.8 dB"]
        }}
    ],
    "skills": [
        "FLAT LIST of EVERY technology, tool, language, framework, platform, database, cloud service mentioned ANYWHERE in the entire resume — deduplicated"
    ],
    "areas_of_interest": ["domains/areas of interest if listed, e.g. AI/ML, Data Science"],
    "soft_skills": ["soft skills if listed, e.g. Leadership, Critical Thinking"],
    "certifications": ["certification names if any"],
    "extra_sections": {{
        "section_name": "content for any resume sections not covered above"
    }}
}}

**Return ONLY the JSON object. No markdown fences, no explanation, no text outside the JSON.**"""


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


# ============================================================================
# Hybrid Matching — LLM Sidecar Assessment Prompt
# ============================================================================

LLM_MATCH_ASSESSMENT_PROMPT = """You are a hiring assessment engine. You receive a candidate's resume data, a job description, and preliminary algorithmic match scores. Your job is to provide a QUALITATIVE assessment that fills gaps the algorithm cannot detect.

The algorithm already computed:
- Embedding-based semantic similarity: {semantic_score}/100
- Keyword + soft skill match: {skill_score}/100 (matched: {matched_skills}, missing: {missing_skills})
- Experience heuristic: {experience_score}/100

**Candidate Resume Data:**
Skills: {resume_skills}
Experience:
{resume_experience}
Projects:
{resume_projects}
Research:
{resume_research}
Areas of Interest: {resume_interests}

**Job Description:**
Title: {jd_title}
Required Skills: {jd_required_skills}
Preferred Skills: {jd_preferred_skills}
Responsibilities:
{jd_responsibilities}
Qualifications:
{jd_qualifications}

**Your task — answer these questions via structured JSON:**

1. TRANSFERABLE SKILLS: Which resume experiences demonstrate competence in JD-required skills even if the exact keyword is absent? Example: candidate built "real-time Tableau dashboard from 15+ APIs" → relevant to "Data Visualization" requirement even though "Data Visualization" is not in their skills list.

2. EXPERIENCE QUALITY: Are the candidate's roles/projects substantive and relevant to the JD, or are they superficial (very short tenures, academic-only, tool-only familiarity without depth)?

3. RISK FLAGS: What are concrete hiring risks? (e.g. no production experience, all internships < 3 months, skills listed but never demonstrated in projects, mismatch between claimed interests and actual work)

4. STRENGTHS: What genuine strengths does this candidate bring to this specific role?

5. FIT SCORE: Given everything above, rate overall candidate-job fit from 0-100. Be calibrated: 70+ means the candidate can meaningfully contribute from day one; 40-69 means trainable but gaps exist; below 40 means significant mismatch.

**Output JSON — return ONLY this structure, no markdown fences, no explanation:**
{{
    "fit_score": 0-100,
    "reasoning": "2-3 sentences explaining the score. Reference specific resume items and JD requirements.",
    "transferable_skills": [
        {{
            "resume_evidence": "specific experience or project bullet from resume",
            "maps_to_requirement": "the JD skill or responsibility it satisfies",
            "confidence": "high|medium|low"
        }}
    ],
    "experience_quality": "strong|moderate|weak|minimal",
    "experience_quality_reasoning": "1 sentence explaining why",
    "risk_flags": [
        "concrete risk statement"
    ],
    "strengths": [
        "concrete strength statement referencing resume evidence"
    ]
}}

**Rules:**
- Be SPECIFIC. Reference actual skills, project names, company names, and JD requirements.
- Do NOT hallucinate skills or experiences not present in the resume data.
- Do NOT give the candidate career advice. You are assessing fit, not coaching.
- Transferable skills must have concrete resume evidence — do not speculate.
- If the algorithm already matched a skill exactly, do NOT repeat it in transferable_skills.
- fit_score must be an integer."""


# Prompt for candidate-JD fit analysis
CANDIDATE_FIT_ANALYSIS_PROMPT = """You are an internal hiring assessment engine that prepares briefing notes for an AI interviewer.

You are NOT interacting with the candidate.
You are preparing operational instructions for the interviewer.

Your output will directly control how the interviewer conducts the interview.

Analyze the candidate’s resume against the job requirements and convert the analysis into interview execution guidance.

Candidate Data:
{resume_summary}

Job Requirements:
{jd_summary}

Match Scores:
- Overall Score: {overall_score}/100
- Skill Match: {skill_score}/100
- Experience Match: {experience_score}/100

Matched Skills: {matched_skills}
Missing Skills: {missing_skills}

Your job:
Determine what must be VERIFIED, CHALLENGED, or PROBED during the interview.

Return JSON in this exact structure:

{
  "fit_assessment": "strong|moderate|weak",

  "verification_targets": [
    "skills or experiences the interviewer must confirm are genuinely understood"
  ],

  "challenge_areas": [
    "claims likely to be superficial or resume-inflated that require deeper questioning"
  ],

  "missing_critical_skills": [
    "required skills not present in the resume that must be tested through questions"
  ],

  "risk_indicators": [
    "possible hiring risks such as shallow project work, tool-only familiarity, short tenures, or inconsistent experience"
  ],

  "interview_plan": {
    "primary_focus": [
      "top priority technical areas to question"
    ],
    "secondary_focus": [
      "additional areas to probe if time allows"
    ],
    "behavioral_checks": [
      "soft skill or communication behaviors to evaluate"
    ],
    "depth_probing_required": true
  },

  "question_strategy": {
    "recommended_question_types": [
      "conceptual",
      "scenario-based",
      "debugging",
      "experience validation"
    ],
    "difficulty_start": "easy|medium|hard",
    "difficulty_ceiling": "medium|hard",
    "when_to_increase_difficulty": "condition describing when interviewer should escalate",
    "when_to_stop_probings": "condition describing when sufficient evidence is collected"
  },

  "hire_signal_logic": {
    "strong_hire_if": [
      "clear evidence patterns indicating strong candidate"
    ],
    "reject_if": [
      "clear failure patterns indicating unsuitable candidate"
    ]
  }
}

Rules:
- Do NOT summarize the candidate.
- Do NOT give career advice.
- Do NOT speak to the candidate.
- Every field must help the interviewer decide the next question.
- Be concrete and reference the job requirements when possible.

Return ONLY valid JSON.
"""
