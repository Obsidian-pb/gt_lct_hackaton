export interface User {
  id: number;
  login: string;
  full_name: string;
  role: 'admin' | 'teacher' | 'student';
  service_name: string | null;
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
