import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { AdminUser, Service, SystemState } from '../api/types';

const ROLE_LABELS: Record<string, string> = {
  admin: 'Администратор',
  teacher: 'Преподаватель',
  student: 'Обучающийся',
};

function CreateForm({
  services,
  onCreated,
}: {
  services: Service[];
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [login, setLogin] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('student');
  const [serviceId, setServiceId] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.createUser({
        login,
        full_name: fullName,
        password,
        role,
        service_id: serviceId ? Number(serviceId) : null,
      });
      setOpen(false);
      setLogin('');
      setFullName('');
      setPassword('');
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось создать учётную запись');
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="actions" style={{ marginBottom: 16 }}>
        <button className="btn" onClick={() => setOpen(true)}>
          Создать учётную запись
        </button>
      </div>
    );
  }

  return (
    <div className="panel-form">
      <div className="field">
        <label htmlFor="login">Логин</label>
        <input id="login" value={login} onChange={(e) => setLogin(e.target.value)} autoFocus />
      </div>
      <div className="field">
        <label htmlFor="full-name">Фамилия, имя, отчество</label>
        <input id="full-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="password">Пароль (не короче 8 символов)</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <div className="field field--narrow">
        <label htmlFor="role">Роль</label>
        <select id="role" value={role} onChange={(e) => setRole(e.target.value)}>
          {Object.entries(ROLE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="service">Служба</label>
        <select id="service" value={serviceId} onChange={(e) => setServiceId(e.target.value)}>
          <option value="">— без привязки —</option>
          {services.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      <button className="btn" onClick={submit} disabled={busy || !login || !fullName || password.length < 8}>
        Создать
      </button>
      <button className="btn btn--ghost" onClick={() => setOpen(false)}>
        Отмена
      </button>
      {error && <div className="alert" style={{ width: '100%' }}>{error}</div>}
    </div>
  );
}

export function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [state, setState] = useState<SystemState | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setUsers(await api.adminUsers());
    setState(await api.adminSystem());
  }, []);

  useEffect(() => {
    reload().catch((e) => setError(e instanceof Error ? e.message : 'Ошибка загрузки'));
    // Справочник служб берётся из того же источника, что и у преподавателя.
    api.adminServices().then(setServices).catch(() => undefined);
  }, [reload]);

  async function toggle(user: AdminUser) {
    try {
      await api.updateUser(user.id, { is_active: !user.is_active });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Операция не выполнена');
    }
  }

  return (
    <>
      <h1 className="page-title">Учётные записи</h1>
      <p className="page-hint">
        Создание учётных записей, назначение ролей и блокировка доступа. Результаты обучения
        администратору не отображаются — это принцип минимальных привилегий.
      </p>

      {state && (
        <div className="stats">
          <div className="stat">
            <div className="stat__value">{state.users_total}</div>
            <div className="stat__label">Учётных записей</div>
            <div className="stat__hint">заблокировано: {state.users_blocked}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{state.ekp_rules}</div>
            <div className="stat__label">Правил классификатора</div>
          </div>
          <div className="stat">
            <div className="stat__value">{state.scenarios_total}</div>
            <div className="stat__label">Учебных сценариев</div>
            <div className="stat__hint">утверждено: {state.scenarios_approved}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{state.attempts_total}</div>
            <div className="stat__label">Выдано карточек</div>
          </div>
          <div className="stat">
            <div className="stat__value">{state.audit_events}</div>
            <div className="stat__label">Событий в журнале</div>
          </div>
          <div className="stat">
            <div className="stat__value" style={{ fontSize: 17 }}>
              {state.llm_provider}
            </div>
            <div className="stat__label">Провайдер ИИ-оценки</div>
            <div className="stat__hint">норматив {state.response_deadline_seconds} с</div>
          </div>
        </div>
      )}

      {error && <div className="alert">{error}</div>}

      <CreateForm services={services} onCreated={() => reload().catch(() => undefined)} />

      <table className="card-table">
        <thead>
          <tr>
            <th>Пользователь</th>
            <th>Роль</th>
            <th>Служба</th>
            <th>Состояние</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id} style={{ cursor: 'default' }}>
              <td>
                <div className="card-table__type">{user.full_name}</div>
                <div className="card-table__address">{user.login}</div>
              </td>
              <td>{ROLE_LABELS[user.role] ?? user.role}</td>
              <td className="card-table__address">{user.service_name ?? '—'}</td>
              <td>
                <span className={user.is_active ? 'chip chip--ok' : 'chip chip--danger'}>
                  {user.is_active ? 'активна' : 'заблокирована'}
                </span>
              </td>
              <td>
                <button className="btn btn--ghost" onClick={() => toggle(user)}>
                  {user.is_active ? 'Заблокировать' : 'Разблокировать'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
