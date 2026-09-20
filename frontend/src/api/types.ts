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
  pickup_deadline_seconds: number;
  handling_deadline_seconds: number;
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



export interface SurveyOption {
  label: string;
  has_children: boolean;
  is_final: boolean;
  incident_type: string | null;
}

export interface Call {
  attempt_id: number;
  legend: string;
  reported_address: string;
  caller: string;
  issued_at: string;
  deadline_seconds: number;
  elapsed_seconds: number;
  finished: boolean;
  chosen_group: string | null;
  chosen_path: string[];
  entered_address: string | null;
  entered_description: string | null;
  audio_url: string | null;
}

export interface Classification {
  correct: boolean;
  chosen_incident_type: string | null;
  expected_incident_type: string;
  matched_depth: number;
  expected_depth: number;
  missed_services: string[];
  extra_services: string[];
  notified_services: Record<string, string>;
}

export interface OperatorEvaluation {
  attempt_id: number;
  score: number;
  violations: Violation[];
  classification: Classification | null;
  llm_pending: boolean;
  llm_available: boolean;
  llm_summary: string | null;
  grammar_issues: string[];
}

export interface AdminUser {
  id: number;
  login: string;
  full_name: string;
  role: string;
  is_active: boolean;
  service_id: number | null;
  service_name: string | null;
  created_at: string;
}

export interface AuditEvent {
  id: number;
  at: string;
  action: string;
  actor_login: string;
  object_type: string | null;
  object_id: number | null;
  detail: Record<string, unknown>;
  ip_address: string | null;
}

export interface SystemState {
  llm_provider: string;
  ekp_rules: number;
  response_deadline_seconds: number;
  users_total: number;
  users_blocked: number;
  scenarios_total: number;
  scenarios_approved: number;
  sessions_total: number;
  attempts_total: number;
  audit_events: number;
}

export interface SessionMember {
  id: number;
  full_name: string;
  service: string | null;
}

export interface SessionScenario {
  id: number;
  title: string;
  approved: boolean;
}

export interface TrainingSession {
  id: number;
  title: string;
  mode: string;
  state: string;
  pickup_deadline_seconds: number;
  handling_deadline_seconds: number;
  call_interval_seconds: number;
  started_at: string | null;
  finished_at: string | null;
  students: SessionMember[];
  scenarios: SessionScenario[];
  approved_scenarios: number;
}

export interface StudentProgress {
  student_id: number;
  student_name: string;
  issued: number;
  opened: number;
  finished: number;
  overdue_pickup: number;
  in_work: number;
}

export interface SessionMonitor {
  session_id: number;
  state: string;
  started_at: string | null;
  call_interval_seconds: number;
  pickup_deadline_seconds: number;
  total_planned: number;
  issued: number;
  finished: number;
  students: StudentProgress[];
}

export interface ModeStats {
  mode: string;
  attempts: number;
  finished: number;
  average_score: number;
  overdue_pickup: number;
}

export interface Work {
  attempt_id: number;
  title: string;
  mode: string;
  finished_at: string;
  score: number;
  violations: number;
  critical: number;
}

export interface Mistake {
  code: string;
  title: string;
  severity: string;
  criterion: string;
  count: number;
  share: number;
  example: string;
}

export interface PersonalProgress {
  student_id: number;
  student_name: string;
  total: number;
  finished: number;
  average_score: number;
  average_pickup_seconds: number | null;
  overdue_pickup: number;
  grammar_issues: number;
  trend: number | null;
  by_mode: ModeStats[];
  mistakes: Mistake[];
  works: Work[];
  advice: string[];
}

/**
 * Материал справочной базы в списке. Текста здесь нет: список открывают,
 * чтобы выбрать нужное, а не чтобы прочитать всё подряд.
 */
export interface Material {
  id: number;
  title: string;
  summary: string | null;
  file_name: string | null;
  media_type: string | null;
  size_bytes: number | null;
  published: boolean;
  author_id: number;
  author_name: string;
  created_at: string;
  /** Правку и публикацию сервер разрешает только автору материала. */
  is_mine: boolean;
}

export interface MaterialDetail extends Material {
  body: string | null;
}
