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

/**
 * Что оператор решает сделать с обращением. Классификация — не единственный
 * правильный ответ: происшествие в другом субъекте передают по
 * принадлежности, а обращение, происшествием не являющееся, не регистрируют.
 */
export type CallOutcome = 'classify' | 'refer' | 'reject';

/**
 * Кем заявитель приходится происшествию. Участник сообщает о себе, очевидец
 * видит со стороны, родственник передаёт с чужих слов — и часто не на месте.
 */
export type CallerRole = 'participant' | 'witness' | 'relative';

export interface Call {
  attempt_id: number;
  legend: string;
  reported_address: string;
  caller: string;
  caller_role: CallerRole | null;
  caller_phone_aon: string | null;
  issued_at: string;
  deadline_seconds: number;
  elapsed_seconds: number;
  finished: boolean;
  chosen_group: string | null;
  chosen_path: string[];
  entered_address: string | null;
  entered_description: string | null;
  chosen_outcome: CallOutcome | null;
  chosen_referral_target: string | null;
  entered_caller_phone: string | null;
  entered_address_parts: Record<string, string>;
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
  expected_outcome: CallOutcome;
  chosen_outcome: CallOutcome | null;
  expected_referral_target: string | null;
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

// --- Доработки кабинета преподавателя ---------------------------------------
// Файл общий, правится только дописыванием в конец, поэтому поля к уже
// описанным сущностям добавлены слиянием объявлений: TypeScript соединяет
// одноимённые интерфейсы одного модуля в один тип.

/** Замечания к тексту сценария после принудительной проверки грамматики. */
export interface GrammarCheck {
  scenario_id: number;
  issues: string[];
  checked_fields: string[];
}

/** Работа обучающегося глазами преподавателя — строка для обратной связи. */
export interface SessionWork {
  attempt_id: number;
  student_id: number;
  student_name: string;
  scenario_title: string;
  finished_at: string | null;
  score: number | null;
  violations: number;
  critical: number;
  teacher_feedback: string | null;
  teacher_feedback_at: string | null;
  teacher_feedback_by: string | null;
}

export interface Evaluation {
  teacher_feedback: string | null;
  teacher_feedback_at: string | null;
  teacher_feedback_by: string | null;
}

export interface Work {
  teacher_feedback: string | null;
  teacher_feedback_by: string | null;
}

export interface Scenario {
  /** Режим обучения: в подборе состава занятия карточки чужого режима не нужны. */
  mode: string;
}

export interface TrainingSession {
  /** Критерии успешности занятия: порог балла и допустимые критические нарушения. */
  pass_score: number;
  max_critical_violations: number;
}

export interface StudentResult {
  critical: number;
  /** null — завершённых работ нет, о зачёте судить не по чему. */
  passed: boolean | null;
}

export interface Report {
  pass_score: number;
  max_critical_violations: number;
  passed_students: number;
  failed_students: number;
}

// --- Учебные группы ---------------------------------------------------------

/** Постоянный список обучающихся: набор курса, смена, поток. */
export interface StudyGroup {
  id: number;
  title: string;
  note: string | null;
  teacher_name: string;
  students: SessionMember[];
}

// --- Состояние комплекса ----------------------------------------------------
// Вид у всех компонентов одинаковый: ok — исправен ли (null, когда судить
// не по чему), note — объяснение по-русски, остальное — числа для показа.

export interface DatabaseState {
  ok: boolean;
  response_ms: number | null;
  note: string;
}

export interface LlmState {
  provider: string;
  model: string;
  ok: boolean | null;
  checked_at: string | null;
  note: string;
}

export interface BackupsState {
  ok: boolean | null;
  last_success_at: string | null;
  age_hours: number | null;
  count: number | null;
  latest_size_bytes: number | null;
  last_failure: string | null;
  note: string;
}

export interface CpuLoad {
  percent: number | null;
  limit_cores: number | null;
  load_average_1m: number | null;
  scope: string;
  note: string;
}

export interface MemoryLoad {
  used_bytes: number | null;
  limit_bytes: number | null;
  percent: number | null;
  scope: string;
  note: string;
}

export interface DiskLoad {
  used_bytes: number | null;
  total_bytes: number | null;
  percent: number | null;
  note: string;
}

export interface SystemHealth {
  at: string;
  started_at: string;
  uptime_seconds: number;
  database: DatabaseState;
  llm: LlmState;
  backups: BackupsState;
  load: { cpu: CpuLoad; memory: MemoryLoad; disk: DiskLoad };
  errors_24h: number | null;
}

/** Одинаковые сбои, сведённые в одну строку отчёта. */
export interface ErrorGroup {
  kind: string;
  message: string;
  count: number;
  last_at: string;
}

export interface ErrorRecord {
  id: number;
  at: string;
  path: string | null;
  method: string | null;
  kind: string;
  message: string;
  traceback: string | null;
  actor_login: string | null;
}

export interface ErrorReport {
  since: string;
  hours: number;
  total: number;
  groups: ErrorGroup[];
  recent: ErrorRecord[];
}

// --- Конфигурация комплекса -------------------------------------------------

/**
 * Настройка языковой модели. Ключа доступа здесь нет и не будет: сервер
 * отдаёт только признак `api_key_set`, прочитать сам ключ нельзя никому.
 */
export interface LlmSettings {
  provider: string;
  base_url: string;
  model: string;
  api_key_set: boolean;
  disable_thinking: boolean;
  /** Уходят ли тексты обучающихся за пределы комплекса. */
  external: boolean;
  timeout_seconds: number;
  updated_at: string | null;
  updated_by: string | null;
}

export interface LoggingSettings {
  audit_retention_days: number;
  level: string;
  /** Нижняя граница из ТЗ: журнал безопасности хранится не менее полугода. */
  min_audit_retention_days: number;
  levels: string[];
  updated_at: string | null;
  updated_by: string | null;
}

export interface SystemSettings {
  llm: LlmSettings;
  logging: LoggingSettings;
  providers: string[];
}

/** Итог проверки связи с моделью — с объяснением, что именно не так. */
export interface LlmTestResult {
  ok: boolean;
  provider: string;
  model: string;
  external: boolean;
  detail: string;
  elapsed_ms: number;
}

// --- Редакции классификатора -------------------------------------------------

/** Редакция ЕКП, загруженная администратором из исходного xlsx. */
export interface ClassifierVersion {
  id: number;
  label: string;
  source_name: string;
  sha256: string;
  rule_count: number;
  is_active: boolean;
  note: string | null;
  uploaded_by: string;
  uploaded_at: string;
  /** Подписи подколонок, которых разбор не знает; приходят только в ответе на загрузку. */
  warnings: string[];
}

export interface ClassifierState {
  builtin_source: string;
  builtin_rule_count: number;
  /** Истинно, когда не включена ни одна загруженная редакция. */
  builtin_active: boolean;
  versions: ClassifierVersion[];
}

export interface TrainingSession {
  /** Обозначение редакции классификатора занятия; null — встроенная из файла поставки. */
  classifier_version_label: string | null;
}
