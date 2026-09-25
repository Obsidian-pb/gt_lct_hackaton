import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { monitoringApi } from '../api/client';
import type { AdminDashboard } from '../api/types';

/**
 * Тот же интервал, что у «Состояния»: главная у администратора открыта
 * подолгу, а состояние комплекса за секунду не меняется.
 */
const REFRESH_MS = 10_000;

/** События, по которым видно попытки подбора пароля и вмешательство в доступ. */
const SECURITY_ACTIONS = new Set([
  'Неудачная попытка входа',
  'Учётная запись заблокирована',
  'Изменён пароль',
]);

function moment(value: string | null): string {
  return value ? new Date(value).toLocaleString('ru-RU') : '—';
}

function Stat({
  label,
  value,
  hint,
  to,
}: {
  label: string;
  value: string;
  hint?: string;
  to: string;
}) {
  return (
    <Link className="stat home-stat home-stat--link" to={to}>
      <div className="stat__value">{value}</div>
      <div className="stat__label">{label}</div>
      {hint && <div className="stat__hint">{hint}</div>}
    </Link>
  );
}

/** Один компонент комплекса: название и чип «исправно / внимание». */
function ComponentChip({ title, ok }: { title: string; ok: boolean | null }) {
  const chip = ok === null ? 'chip chip--neutral' : ok ? 'chip chip--ok' : 'chip chip--danger';
  const label = ok === null ? 'сведений нет' : ok ? 'исправно' : 'внимание';
  return (
    <div className="home-component">
      <span className="home-component__title">{title}</span>
      <span className={chip}>{label}</span>
    </div>
  );
}

export function AdminHomePage() {
  const [data, setData] = useState<AdminDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      monitoringApi
        .dashboard()
        .then((body) => {
          if (!alive) return;
          setData(body);
          setError(null);
        })
        .catch((e) => {
          if (!alive) return;
          setError(e instanceof Error ? e.message : 'Не удалось загрузить сводку');
        });
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!data) {
    return error ? <div className="alert">{error}</div> : <div className="empty">Загрузка…</div>;
  }

  const { system, health, audit, errors } = data;
  // Имя модели показывается, когда оно известно: у заглушки его нет.
  const llmTitle =
    health.llm.model && health.llm.model !== '—'
      ? `Модель ${health.llm.model}`
      : `Языковая модель · ${health.llm.provider}`;

  return (
    <>
      <h1 className="page-title">Главная</h1>
      <p className="page-hint">
        Сводка только показывает. Результатов обучения здесь нет: успеваемость
        обучающихся видит только преподаватель.
      </p>
      {error && <div className="alert">Последнее обновление не удалось: {error}</div>}

      <div className="stats">
        <Stat
          label="учётных записей"
          value={String(system.users_total)}
          hint={system.users_blocked ? `заблокировано: ${system.users_blocked}` : 'заблокированных нет'}
          to="/users"
        />
        <Stat
          label="сценариев"
          value={String(system.scenarios_total)}
          hint={`утверждено: ${system.scenarios_approved}`}
          to="/system"
        />
        <Stat label="занятий" value={String(system.sessions_total)} to="/system" />
        <Stat label="попыток" value={String(system.attempts_total)} to="/system" />
        <Stat label="событий аудита" value={String(system.audit_events)} to="/audit" />
        <Stat
          label="правил ЕКП"
          value={String(system.ekp_rules)}
          hint={`модель: ${system.llm_provider}`}
          to="/classifier"
        />
      </div>

      <h2 className="section-heading">Компоненты</h2>
      <div className="home-components">
        <ComponentChip title="Приложение" ok={true} />
        <ComponentChip title="База данных" ok={health.database.ok} />
        <ComponentChip title={llmTitle} ok={health.llm.ok} />
        <ComponentChip title="Резервные копии" ok={health.backups.ok} />
        <Link className="home-components__more" to="/system">
          подробнее в «Состоянии» →
        </Link>
      </div>

      <div className="home-columns">
        <section>
          <h2 className="section-heading">
            Последние события <Link to="/audit">весь журнал →</Link>
          </h2>
          {audit.length === 0 ? (
            <div className="empty">Событий пока нет.</div>
          ) : (
            <table className="card-table">
              <thead>
                <tr>
                  <th>Время</th>
                  <th>Пользователь</th>
                  <th>Событие</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((event) => (
                  <tr key={event.id} style={{ cursor: 'default' }}>
                    <td style={{ whiteSpace: 'nowrap' }}>{moment(event.at)}</td>
                    <td>{event.actor_login}</td>
                    <td>
                      <span
                        className={
                          SECURITY_ACTIONS.has(event.action)
                            ? 'chip chip--danger'
                            : 'chip chip--neutral'
                        }
                      >
                        {event.action}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section>
          <h2 className="section-heading">
            Сбои за сутки
            {health.errors_24h !== null && (
              <span className={health.errors_24h ? 'chip chip--danger' : 'chip chip--ok'}>
                {health.errors_24h}
              </span>
            )}
          </h2>
          {errors.length === 0 ? (
            <div className="empty">За сутки сбоев не было.</div>
          ) : (
            <table className="card-table">
              <thead>
                <tr>
                  <th>Ошибка</th>
                  <th>Раз</th>
                  <th>В последний раз</th>
                </tr>
              </thead>
              <tbody>
                {errors.map((group) => (
                  <tr key={`${group.kind}|${group.message}`} style={{ cursor: 'default' }}>
                    <td className="card-table__address">
                      <span className="chip chip--danger">{group.kind}</span> {group.message}
                    </td>
                    <td>{group.count}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{moment(group.last_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </>
  );
}
