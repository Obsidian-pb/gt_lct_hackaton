import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { AuditEvent } from '../api/types';

/** События, по которым видно попытки подбора пароля и вмешательство в доступ. */
const SECURITY_ACTIONS = new Set([
  'Неудачная попытка входа',
  'Учётная запись заблокирована',
  'Изменён пароль',
]);

function formatDetail(detail: Record<string, unknown>): string {
  const entries = Object.entries(detail);
  if (entries.length === 0) return '—';
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join('; ');
}

export function AdminAuditPage() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.auditActions().then(setActions).catch(() => undefined);
  }, []);

  useEffect(() => {
    api
      .auditLog(filter || undefined)
      .then(setEvents)
      .catch((e) => setError(e instanceof Error ? e.message : 'Не удалось загрузить журнал'));
  }, [filter]);

  if (error) return <div className="alert">{error}</div>;
  if (!events) return <div className="empty">Загрузка журнала…</div>;

  return (
    <>
      <h1 className="page-title">Журнал аудита</h1>
      <p className="page-hint">
        Протоколируются вход в систему, изменения учётных записей и действия со сценариями.
        Записи хранятся не менее шести месяцев, как требует техническое задание.
      </p>

      <div className="field" style={{ maxWidth: 420 }}>
        <label htmlFor="action">Событие</label>
        <select id="action" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">все события</option>
          {actions.map((action) => (
            <option key={action} value={action}>
              {action}
            </option>
          ))}
        </select>
      </div>

      {events.length === 0 ? (
        <div className="empty">Событий не найдено.</div>
      ) : (
        <table className="card-table">
          <thead>
            <tr>
              <th>Время</th>
              <th>Пользователь</th>
              <th>Событие</th>
              <th>Подробности</th>
              <th>Адрес</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id} style={{ cursor: 'default' }}>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {new Date(event.at).toLocaleString('ru-RU')}
                </td>
                <td>{event.actor_login}</td>
                <td>
                  <span
                    className={
                      SECURITY_ACTIONS.has(event.action) ? 'chip chip--danger' : 'chip chip--neutral'
                    }
                  >
                    {event.action}
                  </span>
                </td>
                <td className="card-table__address">{formatDetail(event.detail)}</td>
                <td className="card-table__address">{event.ip_address ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
