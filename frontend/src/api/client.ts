import type {
  Card,
  Catalog,
  Evaluation,
  GenerateResult,
  Report,
  Scenario,
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
  scenarios: (approved?: boolean) =>
    request<Scenario[]>(
      `/api/teacher/scenarios${approved === undefined ? '' : `?approved=${approved}`}`,
    ),
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
  sessions: () => request<TrainingSession[]>('/api/teacher/sessions'),
  report: (id: number) => request<Report>(`/api/teacher/sessions/${id}/report`),
};
