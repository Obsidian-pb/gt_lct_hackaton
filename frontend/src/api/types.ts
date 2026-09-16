export interface User {
  id: number;
  login: string;
  full_name: string;
  role: 'admin' | 'teacher' | 'student';
  service_name: string | null;
  service_ekp_name: string | null;
}

export interface Card {
  attempt_id: number;
  incident_type: string;
  address: string;
  description: string;
  caller: string;
  /** Службы из списка оповещения ЕКП и тип происшествия в системе каждой из них. */
  notified_services: Record<string, string>;
  issued_at: string;
  opened_at: string | null;
  deadline_seconds: number;
  elapsed_seconds: number;
  current_status: string | null;
  available_statuses: string[];
  comment_required_for: string[];
  card_status: string;
  finished: boolean;
}

export interface Violation {
  code: string;
  title: string;
  criterion: string;
  severity: 'критическое' | 'существенное' | 'замечание';
  detail: string;
  evidence: string | null;
  example: string | null;
}

export interface Evaluation {
  attempt_id: number;
  score: number;
  criteria: Record<string, boolean>;
  violations: Violation[];
  llm_pending: boolean;
  llm_available: boolean;
  llm_summary: string | null;
  grammar_issues: string[];
}

export interface Service {
  id: number;
  name: string;
}

export interface Catalog {
  groups: string[];
  services: Service[];
  difficulties: Record<string, string>;
}

export interface Scenario {
  id: number;
  title: string;
  incident_type: string;
  address: string;
  description: string;
  caller: string;
  difficulty: number;
  source: string;
  expected_primary_status: string;
  is_profile: boolean;
  required_comment_points: string[];
  service_name: string;
  notified_services: Record<string, string>;
  approved: boolean;
  approved_at: string | null;
  teacher_note: string | null;
}

export interface GenerateResult {
  requested: number;
  created: number;
  scenarios: Scenario[];
  warning: string | null;
}

export interface StudentResult {
  student_id: number;
  student_name: string;
  attempts: number;
  finished: number;
  average_score: number;
  overdue: number;
  violations: Record<string, number>;
}

export interface Report {
  session_id: number;
  title: string;
  state: string;
  deadline_seconds: number;
  started_at: string | null;
  finished_at: string | null;
  students: StudentResult[];
  total_attempts: number;
  finished_attempts: number;
  average_score: number;
  average_response_seconds: number | null;
  overdue_share: number;
  violations: Record<string, number>;
  grammar_issues: number;
  insights: string[];
}

export interface TrainingSession {
  id: number;
  title: string;
  state: string;
  deadline_seconds: number;
}
