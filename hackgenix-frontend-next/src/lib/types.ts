// ============================================================
// TypeScript types matching the HackGeniX backend API models
// ============================================================

// --- Auth ---
export type Role = 'admin' | 'hiring_manager' | 'interviewer' | 'candidate';

export interface AuthUser {
  id: string;
  role: Role;
  permissions: string[];
  token: string;
}

export const ROLE_PERMISSIONS: Record<Role, string[]> = {
  admin: ['all'],
  hiring_manager: [
    'create_interview', 'view_interview', 'manage_interview', 'conduct_interview',
    'create_session', 'view_session', 'update_session', 'delete_session', 'participate_session',
    'create_candidate', 'view_candidate', 'update_candidate',
    'upload_document', 'view_document', 'delete_document',
    'generate_questions', 'view_questions',
    'view_reports', 'generate_reports',
    'view_analysis', 'use_voice',
  ],
  interviewer: [
    'view_interview', 'conduct_interview',
    'view_session', 'update_session',
    'view_candidate', 'view_document', 'view_questions',
    'view_reports', 'use_voice', 'view_analysis',
  ],
  candidate: ['participate_session', 'use_voice'],
};

// --- Documents ---
export interface Resume {
  id: string;
  filename: string;
  candidate_name?: string;
  skills?: string[];
  experience_years?: number;
  uploaded_at: string;
  status: string;
}

export interface JobDescription {
  id: string;
  title: string;
  company?: string;
  required_skills?: string[];
  experience_required?: string;
  created_at: string;
  status: string;
}

export interface MatchResult {
  overall_score: number;
  skill_match: number;
  experience_match: number;
  recommendations: string[];
}

// --- Sessions ---
export type SessionStatus =
  | 'created'
  | 'in_progress'
  | 'paused'
  | 'completed'
  | 'cancelled';

export type InterviewStage =
  | 'screening'
  | 'technical'
  | 'behavioral'
  | 'system_design';

export interface SessionSummary {
  id: string;
  resume_id: string;
  job_description_id: string;
  status: SessionStatus;
  current_stage?: InterviewStage;
  created_at: string;
  updated_at?: string;
  total_questions?: number;
  answered_questions?: number;
}

export interface SessionDetail extends SessionSummary {
  current_question?: Question;
  answers: Answer[];
  config: InterviewConfig;
  progress?: InterviewProgress;
}

export interface Question {
  id: string;
  text: string;
  type: InterviewStage;
  difficulty?: string;
  duration_seconds?: number;
  is_follow_up?: boolean;
  sub_question_label?: string;
  follow_up_count?: number;
  parent_question_id?: string;
}

export interface Answer {
  question_id: string;
  answer_text: string;
  evaluation?: Evaluation;
  answered_at: string;
}

export interface Evaluation {
  score: number;
  strengths: string[];
  improvements: string[];
  recommendation: string;
  detailed_feedback?: string;
}

export interface InterviewProgress {
  current_question_number: number;
  total_questions: number;
  current_stage: InterviewStage;
  stages_completed: InterviewStage[];
  percentage: number;
}

// --- Interview Config ---
export interface InterviewConfig {
  resume_id?: string;
  job_description_id?: string;
  questions?: {
    screening?: number;
    technical?: number;
    behavioral?: number;
    system_design?: number;
  };
  time_limits?: {
    max_duration_seconds?: number;
    question_timeout_seconds?: number;
  };
  adaptive?: {
    adaptive_difficulty?: boolean;
    enable_question_augmentation?: boolean;
  };
  follow_ups?: {
    enabled?: boolean;
    max_per_question?: number;
    max_after_dont_know?: number;
    require_depth_increase?: boolean;
    allow_different_angle_on_failure?: boolean;
    trigger_rules?: {
      poor_score_threshold?: number;
      standout_score_threshold?: number;
      hooks_trigger_alone?: boolean;
    };
  };
  voice?: {
    tts_voice?: string | null;
    stt_model?: string;
  };
}

// --- Reports ---
export interface Report {
  session_id: string;
  candidate_name?: string;
  job_title?: string;
  overall_score: number;
  stage_scores: Record<string, number>;
  total_questions: number;
  total_answered: number;
  strengths: string[];
  improvements: string[];
  recommendation: string;
  detailed_analysis?: string;
  created_at: string;
}

// --- SSE Event ---
export interface SSEEvent {
  event?: string;
  data: string;
}

// --- WebSocket Messages ---
export interface WSMessage {
  type: string;
  [key: string]: unknown;
}

export interface WSQuestionMessage extends WSMessage {
  type: 'question';
  question: Question;
  duration_seconds?: number;
  is_follow_up?: boolean;
  sub_question_label?: string;
  follow_up_count?: number;
}

export interface WSEvaluationMessage extends WSMessage {
  type: 'evaluation';
  evaluation: Evaluation;
  follow_up_count?: number;
}

export interface WSConnectedMessage extends WSMessage {
  type: 'connected';
  session_id: string;
  message: string;
}

export interface WSProgressMessage extends WSMessage {
  type: 'progress';
  current_question: number;
  total_questions: number;
  current_stage: string;
}

export interface WSTimerMessage extends WSMessage {
  type: 'timer_warning' | 'timer_expired';
  remaining_seconds?: number;
}

export interface WSErrorMessage extends WSMessage {
  type: 'error';
  message: string;
  recoverable: boolean;
}

// --- Health ---
export interface HealthStatus {
  status: string;
  version?: string;
  components?: Record<string, { status: string; details?: string }>;
}
