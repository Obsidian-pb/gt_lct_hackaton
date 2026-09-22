import type {
  AdminUser,
  AuditEvent,
  Call,
  CallOutcome,
  Card,
  Catalog,
  Evaluation,
  GenerateResult,
  OperatorEvaluation,
  Report,
  Scenario,
  Service,
  SessionMember,
  SessionMonitor,
  PersonalProgress,
  SurveyOption,
  SystemState,
  TrainingSession,
  User,
} from './types';

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';
const TOKEN_KEY = 'arm112.token';

export class ApiError extends Error {}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });

  if (!response.ok) {
    let detail = `Ошибка ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // Тело может быть пустым — оставляем текст по умолчанию.
    }
    throw new ApiError(detail);
  }
  return response.json() as Promise<T>;
}

/** Файл выгрузки: не JSON, но заголовок авторизации нужен такой же. */
async function download(path: string, fallbackName: string): Promise<void> {
  const token = getToken();
  const response = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new ApiError(`Не удалось выгрузить отчёт (${response.status})`);

  // Имя файла задаёт сервер: в нём номер занятия и дата.
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const ascii = /filename="([^"]+)"/.exec(disposition);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = ascii ? ascii[1] : fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Память под blob браузер сам не освобождает, но освобождать её сразу
  // нельзя: часть браузеров не успевает начать сохранение и обрывает его.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export async function login(username: string, password: string): Promise<void> {
  const body = new URLSearchParams({ username, password });
  const response = await fetch(`${BASE}/api/auth/token`, { method: 'POST', body });
  if (!response.ok) throw new ApiError('Неверный логин или пароль');
  const data = (await response.json()) as { access_token: string };
  setToken(data.access_token);
}

export const api = {
  me: () => request<User>('/api/auth/me'),
  myCards: () => request<Card[]>('/api/attempts/my'),
  card: (id: number) => request<Card>(`/api/attempts/${id}`),
  openCard: (id: number) => request<Card>(`/api/attempts/${id}/open`, { method: 'POST' }),
  setStatus: (id: number, status: string, comment: string | null) =>
    request<Card>(`/api/attempts/${id}/status`, {
      method: 'POST',
      body: JSON.stringify({ status, comment }),
    }),
  finish: (id: number) => request<Evaluation>(`/api/attempts/${id}/finish`, { method: 'POST' }),
  evaluation: (id: number) => request<Evaluation>(`/api/attempts/${id}/evaluation`),

  catalog: () => request<Catalog>('/api/teacher/catalog'),
  scenarios: (approved?: boolean, mode?: string) => {
    const query = new URLSearchParams();
    if (approved !== undefined) query.set('approved', String(approved));
    if (mode) query.set('mode', mode);
    const suffix = query.toString();
    return request<Scenario[]>(`/api/teacher/scenarios${suffix ? `?${suffix}` : ''}`);
  },
  generate: (group: string, count: number, difficulty: number, serviceId: number) =>
    request<GenerateResult>('/api/teacher/scenarios/generate', {
      method: 'POST',
      body: JSON.stringify({ group, count, difficulty, service_id: serviceId }),
    }),
  approveScenario: (id: number) =>
    request<Scenario>(`/api/teacher/scenarios/${id}/approve`, { method: 'POST' }),
  correctScenario: (id: number, note: string) =>
    request<Scenario>(`/api/teacher/scenarios/${id}/correct`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),
  myCalls: () => request<Call[]>('/api/operator/calls/my'),
  call: (id: number) => request<Call>(`/api/operator/calls/${id}`),
  surveyGroups: () => request<string[]>('/api/operator/groups'),
  surveyOptions: (group: string, path: string[]) =>
    request<SurveyOption[]>(
      `/api/operator/options?group=${encodeURIComponent(group)}&path=${encodeURIComponent(
        path.join('|'),
      )}`,
    ),
  classifyCall: (
    id: number,
    body: {
      outcome: CallOutcome;
      referral_target?: string;
      group: string;
      path: string[];
      address: string;
      description: string;
      caller_phone?: string;
    },
  ) =>
    request<OperatorEvaluation>(`/api/operator/calls/${id}/classify`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  sessions: () => request<TrainingSession[]>('/api/teacher/sessions'),
  sessionStudents: () => request<SessionMember[]>('/api/teacher/students'),
  createSession: (body: {
    title: string;
    mode: string;
    pickup_deadline_seconds: number;
    handling_deadline_seconds: number;
    call_interval_seconds: number;
  }) =>
    request<TrainingSession>('/api/teacher/sessions', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateSession: (id: number, body: Record<string, unknown>) =>
    request<TrainingSession>(`/api/teacher/sessions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  startSession: (id: number) =>
    request<TrainingSession>(`/api/teacher/sessions/${id}/start`, { method: 'POST' }),
  finishSession: (id: number) =>
    request<TrainingSession>(`/api/teacher/sessions/${id}/finish`, { method: 'POST' }),
  monitorSession: (id: number) =>
    request<SessionMonitor>(`/api/teacher/sessions/${id}/monitor`),
  report: (id: number) => request<Report>(`/api/teacher/sessions/${id}/report`),
  downloadReport: (id: number, format: 'csv' | 'pdf') =>
    download(`/api/teacher/sessions/${id}/report.${format}`, `report-session-${id}.${format}`),

  progress: (studentId?: number) =>
    request<PersonalProgress>(
      `/api/student/progress${studentId ? `?student_id=${studentId}` : ''}`,
    ),

  adminUsers: () => request<AdminUser[]>('/api/admin/users'),
  adminServices: () => request<Service[]>('/api/admin/services'),
  adminSystem: () => request<SystemState>('/api/admin/system'),
  createUser: (body: {
    login: string;
    full_name: string;
    password: string;
    role: string;
    service_id: number | null;
  }) =>
    request<AdminUser>('/api/admin/users', { method: 'POST', body: JSON.stringify(body) }),
  updateUser: (id: number, body: Record<string, unknown>) =>
    request<AdminUser>(`/api/admin/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  auditLog: (action?: string) =>
    request<AuditEvent[]>(
      `/api/admin/audit${action ? `?action=${encodeURIComponent(action)}` : ''}`,
    ),
  auditActions: () => request<string[]>('/api/admin/audit/actions'),
};

// Импорт типов справочной базы стоит здесь, а не в общем списке наверху:
// раздел добавлен отдельным блоком, и так его правки не пересекаются
// с правками остальных разделов в этом же файле.
import type { Material, MaterialDetail } from './types';

/**
 * Справочная база учебных материалов.
 *
 * Загрузка файла идёт мимо `request`: там к телу подставляется
 * Content-Type application/json, а multipart обязан нести границу частей,
 * и её проставляет сам браузер — свой заголовок её бы затёр.
 */
async function uploadMaterialFile(id: number, file: File): Promise<MaterialDetail> {
  const token = getToken();
  const form = new FormData();
  form.append('file', file);
  const response = await fetch(`${BASE}/api/materials/${id}/file`, {
    method: 'POST',
    body: form,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    let detail = `Ошибка ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // Тело может быть пустым — оставляем текст по умолчанию.
    }
    throw new ApiError(detail);
  }
  return (await response.json()) as MaterialDetail;
}

export const materialsApi = {
  list: () => request<Material[]>('/api/materials'),
  read: (id: number) => request<MaterialDetail>(`/api/materials/${id}`),
  create: (body: { title: string; summary: string | null; body: string | null }) =>
    request<MaterialDetail>('/api/materials', { method: 'POST', body: JSON.stringify(body) }),
  update: (id: number, body: Record<string, unknown>) =>
    request<MaterialDetail>(`/api/materials/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  remove: async (id: number): Promise<void> => {
    const token = getToken();
    const response = await fetch(`${BASE}/api/materials/${id}`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    // Ответ на удаление пустой (204), и `request` споткнулся бы о разбор JSON.
    if (!response.ok) throw new ApiError(`Не удалось удалить материал (${response.status})`);
  },
  publish: (id: number) =>
    request<MaterialDetail>(`/api/materials/${id}/publish`, { method: 'POST' }),
  unpublish: (id: number) =>
    request<MaterialDetail>(`/api/materials/${id}/unpublish`, { method: 'POST' }),
  upload: uploadMaterialFile,
  // Имя файла приходит с сервера в Content-Disposition; запасное нужно
  // только на случай, если заголовок потеряется на обратном прокси.
  download: (id: number, fallbackName: string) =>
    download(`/api/materials/${id}/file`, fallbackName),
};

// --- Доработки кабинета преподавателя ---------------------------------------
// Файл общий и правится только дописыванием в конец, поэтому новые вызовы
// собраны отдельным объектом, а не добавлены в api выше, а типы для них
// импортированы отдельной строкой, а не в общий список в начале файла.
import type { GrammarCheck, SessionWork } from './types';

export const teacherApi = {
  /** Принудительная проверка грамматики текста сценария. Ничего не меняет. */
  checkGrammar: (scenarioId: number) =>
    request<GrammarCheck>(`/api/teacher/scenarios/${scenarioId}/grammar`, {
      method: 'POST',
    }),
  /** Сценарии нужного уровня сложности — для подбора состава занятия. */
  scenariosByDifficulty: (approved: boolean, mode: string, difficulty: number | null) => {
    const query = new URLSearchParams({ approved: String(approved), mode });
    if (difficulty !== null) query.set('difficulty', String(difficulty));
    return request<Scenario[]>(`/api/teacher/scenarios?${query.toString()}`);
  },
  /**
   * Создание занятия вместе с критериями успешности. Повторяет api.createSession
   * не по прихоти: тип тела там перечисляет поля поимённо, а дописывать в него
   * новые нельзя — файл общий и правится только добавлением в конец.
   */
  createSession: (body: {
    title: string;
    mode: string;
    pickup_deadline_seconds: number;
    handling_deadline_seconds: number;
    call_interval_seconds: number;
    pass_score: number;
    max_critical_violations: number;
  }) =>
    request<TrainingSession>('/api/teacher/sessions', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  sessionWorks: (sessionId: number) =>
    request<SessionWork[]>(`/api/teacher/sessions/${sessionId}/works`),
  leaveFeedback: (attemptId: number, text: string) =>
    request<SessionWork>(`/api/teacher/attempts/${attemptId}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
};

// --- Учебные группы ---------------------------------------------------------

import type { StudyGroup } from './types';

export const groupsApi = {
  list: () => request<StudyGroup[]>('/api/teacher/groups'),
  create: (body: { title: string; note?: string | null; student_ids?: number[] }) =>
    request<StudyGroup>('/api/teacher/groups', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  update: (
    id: number,
    body: { title?: string; note?: string | null; student_ids?: number[] },
  ) =>
    request<StudyGroup>(`/api/teacher/groups/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  remove: (id: number) =>
    request<void>(`/api/teacher/groups/${id}`, { method: 'DELETE' }),
};

// --- Состояние комплекса ----------------------------------------------------
// Файл общий и правится только дописыванием в конец, поэтому раздел вынесен
// отдельным объектом, а его типы импортированы отдельной строкой.

import type { ErrorReport, SystemHealth } from './types';

export const monitoringApi = {
  /** Состояние компонентов и нагрузка на сервер на текущий момент. */
  health: () => request<SystemHealth>('/api/admin/health'),
  /** Отчёт об ошибках и сбоях за последние `hours` часов. */
  errors: (hours: number) => request<ErrorReport>(`/api/admin/errors?hours=${hours}`),
};

// --- Конфигурация комплекса -------------------------------------------------

import type { LlmSettings, LlmTestResult, LoggingSettings, SystemSettings } from './types';

export const settingsApi = {
  read: () => request<SystemSettings>('/api/admin/settings'),
  /** Пустой api_key означает «не менять»: ключ обратно в форму не приходит. */
  saveLlm: (body: {
    provider: string;
    base_url: string;
    model: string;
    api_key: string;
    disable_thinking: boolean;
  }) =>
    request<LlmSettings>('/api/admin/settings/llm', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  clearLlmKey: () =>
    request<LlmSettings>('/api/admin/settings/llm/key/clear', { method: 'POST' }),
  saveLogging: (body: { audit_retention_days: number; level: string }) =>
    request<LoggingSettings>('/api/admin/settings/logging', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  /** Проверка связи на ещё не сохранённой настройке — до её применения. */
  testLlm: (body: {
    provider: string;
    base_url: string;
    model: string;
    api_key: string;
    disable_thinking: boolean;
  }) =>
    request<LlmTestResult>('/api/admin/llm/test', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};
