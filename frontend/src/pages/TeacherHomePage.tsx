import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { teacherApi } from '../api/client';
import type { TeacherDashboard } from '../api/types';
import { MODE_LABELS } from './TeacherSessionsPage';

/**
 * Главная обновляется раз в полминуты. Идущее занятие меняется само по себе —
 * вызовы поступают по расписанию, — но следить за ним по секундам преподаватель
 * будет на странице занятия, а не здесь.
 */
const REFRESH_MS = 30_000;

/** Плитка сводки. Ссылка ведёт туда, где с этим числом что-то делают. */
function Stat({
  label,
  value,
  hint,
  to,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  to?: string;
  tone?: 'ok' | 'bad';
}) {
  const valueClass = `stat__value${tone ? ` stat__value--${tone}` : ''}`;
  const body = (
    <>
      <div className={valueClass}>{value}</div>
      <div className="stat__label">{label}</div>
      {hint && <div className="stat__hint">{hint}</div>}
    </>
  );
  return to ? (
    <Link className="stat home-stat home-stat--link" to={to}>
      {body}
    </Link>
  ) : (
    <div className="stat home-stat">{body}</div>
  );
}

function moment(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function TeacherHomePage() {
  const [data, setData] = useState<TeacherDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      teacherApi
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

  const percent = (share: number | null) => (share === null ? '—' : `${Math.round(share * 100)}`);
  // Что ждёт действий преподавателя. Пустой список — тоже ответ: сегодня
  // ничего не накопилось, и об этом сказано прямо, а не пустым местом.
  const attention: { text: string; to: string }[] = [];
  if (data.scenarios_pending > 0) {
    attention.push({
      text: `Ждут утверждения: ${data.scenarios_pending}`,
      to: '/scenarios',
    });
  }
  if (data.feedback_missing > 0) {
    attention.push({
      text: `Работ за неделю без примечания преподавателя: ${data.feedback_missing}`,
      to: '/report',
    });
  }

  return (
    <>
      <h1 className="page-title">Главная</h1>
      <p className="page-hint">
        Что идёт прямо сейчас и что ждёт вашего решения. Показатели за неделю считаются
        по первым попыткам, как и в отчёте занятия.
      </p>
      {error && <div className="alert">Последнее обновление не удалось: {error}</div>}

      <div className="stats">
        <Stat label="идут сейчас" value={String(data.active_sessions)} to="/sessions" />
        <Stat label="обучающихся" value={String(data.students_total)} to="/groups" />
        <Stat
          label="ждут утверждения"
          value={String(data.scenarios_pending)}
          hint="сценариев"
          to="/scenarios"
          tone={data.scenarios_pending ? 'bad' : undefined}
        />
        <Stat label="учебных групп" value={String(data.groups_total)} to="/groups" />
        <Stat label="работ за 7 суток" value={String(data.works_7d)} to="/report" />
        <Stat
          label="средний балл"
          value={percent(data.average_score_7d)}
          hint="из 100, за 7 суток"
          tone={
            data.average_score_7d === null
              ? undefined
              : data.average_score_7d >= 0.7
                ? 'ok'
                : 'bad'
          }
        />
        <Stat
          label="зачтено"
          value={data.passed_share_7d === null ? '—' : `${percent(data.passed_share_7d)}%`}
          hint="доля работ за 7 суток"
        />
        <Stat
          label="без примечания"
          value={String(data.feedback_missing)}
          hint="работ за 7 суток"
          to="/report"
          tone={data.feedback_missing ? 'bad' : undefined}
        />
      </div>

      {attention.length > 0 && (
        <ul className="home-attention">
          {attention.map((item) => (
            <li key={item.to}>
              <Link to={item.to}>{item.text} →</Link>
            </li>
          ))}
        </ul>
      )}

      <h2 className="section-heading">Идут сейчас</h2>
      {data.sessions.length === 0 ? (
        <div className="empty">
          Сейчас занятий нет. Запустить занятие можно в разделе{' '}
          <Link to="/sessions">«Занятия»</Link>.
        </div>
      ) : (
        <table className="card-table">
          <thead>
            <tr>
              <th>Занятие</th>
              <th>Кого обучаем</th>
              <th>Обучающихся</th>
              <th>Поступило</th>
              <th>Обработано</th>
            </tr>
          </thead>
          <tbody>
            {data.sessions.map((s) => (
              <tr key={s.id} style={{ cursor: 'default' }}>
                <td className="card-table__type">
                  <Link to={`/sessions/${s.id}`}>{s.title}</Link>
                </td>
                <td>{MODE_LABELS[s.mode] ?? s.mode}</td>
                <td>{s.students}</td>
                <td>{s.issued}</td>
                <td>{s.finished}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2 className="section-heading">Последние работы</h2>
      {data.recent_works.length === 0 ? (
        <div className="empty">Завершённых работ пока нет.</div>
      ) : (
        <table className="card-table">
          <thead>
            <tr>
              <th>Обучающийся</th>
              <th>Карточка</th>
              <th>Занятие</th>
              <th>Балл</th>
              <th>Завершена</th>
              <th>Примечание</th>
            </tr>
          </thead>
          <tbody>
            {data.recent_works.map((w) => (
              <tr key={w.attempt_id} style={{ cursor: 'default' }}>
                <td className="card-table__type">{w.student_name}</td>
                <td className="card-table__address">{w.scenario_title}</td>
                <td>
                  <Link to={`/report?session=${w.session_id}`}>{w.session_title}</Link>
                </td>
                <td>
                  <span className={w.score >= 0.7 ? 'chip chip--ok' : 'chip chip--danger'}>
                    {Math.round(w.score * 100)}
                  </span>
                  {w.critical > 0 && (
                    <span className="chip chip--danger home-chip-gap">
                      критических: {w.critical}
                    </span>
                  )}
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>{moment(w.finished_at)}</td>
                <td>
                  {w.has_feedback ? (
                    <span className="chip chip--neutral">есть</span>
                  ) : (
                    <Link to={`/report?session=${w.session_id}`}>оставить</Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
