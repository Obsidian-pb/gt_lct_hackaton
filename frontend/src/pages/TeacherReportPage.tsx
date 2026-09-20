import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Report, TrainingSession } from '../api/types';
import { VIOLATION_TITLES } from '../violations';

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat__value">{value}</div>
      <div className="stat__label">{label}</div>
      {hint && <div className="stat__hint">{hint}</div>}
    </div>
  );
}

/** Горизонтальная шкала: доля карточек, где встретилось нарушение. */
function ViolationBar({ code, count, total }: { code: string; count: number; total: number }) {
  const share = total ? count / total : 0;
  return (
    <div className="bar">
      <div className="bar__head">
        <span className="violation__code">{code}</span>
        <span className="bar__title">{VIOLATION_TITLES[code] ?? code}</span>
        <span className="bar__value">
          {count} · {Math.round(share * 100)}%
        </span>
      </div>
      <div className="bar__track">
        <div className="bar__fill" style={{ width: `${Math.max(share * 100, 2)}%` }} />
      </div>
    </div>
  );
}

export function TeacherReportPage() {
  // Занятие можно открыть по ссылке сразу после завершения.
  const [params] = useSearchParams();
  const requested = Number(params.get('session')) || null;
  const [sessions, setSessions] = useState<TrainingSession[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(requested);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Пока файл готовится, кнопки заблокированы: PDF на большом занятии
  // собирается не мгновенно, а повторные щелчки скачали бы его дважды.
  const [saving, setSaving] = useState<'csv' | 'pdf' | null>(null);
  // Неудача выгрузки не должна прятать сам отчёт, поэтому она хранится
  // отдельно от ошибки загрузки страницы.
  const [savingError, setSavingError] = useState<string | null>(null);

  async function save(format: 'csv' | 'pdf') {
    if (sessionId == null) return;
    setSaving(format);
    setSavingError(null);
    try {
      await api.downloadReport(sessionId, format);
    } catch (e) {
      setSavingError(e instanceof Error ? e.message : 'Не удалось выгрузить отчёт');
    } finally {
      setSaving(null);
    }
  }

  useEffect(() => {
    api
      .sessions()
      .then((list) => {
        setSessions(list);
        setSessionId((current) => current ?? list[0]?.id ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Не удалось загрузить занятия'));
  }, []);

  useEffect(() => {
    if (sessionId == null) return;
    api
      .report(sessionId)
      .then(setReport)
      .catch((e) => setError(e instanceof Error ? e.message : 'Не удалось построить отчёт'));
  }, [sessionId]);

  if (error) return <div className="alert">{error}</div>;
  if (!report) return <div className="empty">Загрузка отчёта…</div>;

  const finished = report.finished_attempts;

  return (
    <>
      <h1 className="page-title">Отчёт о практическом занятии</h1>
      <p className="page-hint">
        Действия обучающихся, замечания, время обработки карточки и отклонение от норматива.
      </p>

      {sessions.length > 1 && (
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="session">Занятие</label>
          <select
            id="session"
            value={sessionId ?? ''}
            onChange={(e) => setSessionId(Number(e.target.value))}
          >
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="actions">
        <button className="btn btn--ghost" disabled={saving !== null} onClick={() => save('csv')}>
          {saving === 'csv' ? 'Готовим CSV…' : 'Выгрузить в CSV'}
        </button>
        <button className="btn btn--ghost" disabled={saving !== null} onClick={() => save('pdf')}>
          {saving === 'pdf' ? 'Готовим PDF…' : 'Выгрузить в PDF'}
        </button>
      </div>
      {savingError && <div className="alert">{savingError}</div>}

      <div className="stats">
        <Stat label="Карточек выдано" value={String(report.total_attempts)} />
        <Stat label="Завершено" value={String(finished)} />
        <Stat
          label="Средний балл"
          value={finished ? `${Math.round(report.average_score * 100)}` : '—'}
          hint="из 100"
        />
        <Stat
          label="Среднее время до ответа"
          value={
            report.average_response_seconds != null
              ? `${report.average_response_seconds} с`
              : '—'
          }
          hint={`норматив ${report.pickup_deadline_seconds} с`}
        />
        <Stat
          label="Просрочен норматив"
          value={`${Math.round(report.overdue_share * 100)}%`}
          hint="доля карточек"
        />
        <Stat label="Замечаний к грамматике" value={String(report.grammar_issues)} />
      </div>

      <h2 className="section-heading">Выводы по группе</h2>
      <ul className="insights">
        {report.insights.map((insight, index) => (
          <li key={index}>{insight}</li>
        ))}
      </ul>

      {Object.keys(report.violations).length > 0 && (
        <>
          <h2 className="section-heading">Типичные нарушения</h2>
          {Object.entries(report.violations)
            .sort(([, a], [, b]) => b - a)
            .map(([code, count]) => (
              <ViolationBar key={code} code={code} count={count} total={finished} />
            ))}
        </>
      )}

      <h2 className="section-heading">Обучающиеся</h2>
      <table className="card-table">
        <thead>
          <tr>
            <th>Обучающийся</th>
            <th>Карточек</th>
            <th>Завершено</th>
            <th>Средний балл</th>
            <th>Просрочек</th>
          </tr>
        </thead>
        <tbody>
          {report.students.map((student) => (
            <tr key={student.student_id}>
              <td>{student.student_name}</td>
              <td>{student.attempts}</td>
              <td>{student.finished}</td>
              <td>
                {student.finished ? (
                  <span
                    className={
                      student.average_score >= 0.7 ? 'chip chip--ok' : 'chip chip--danger'
                    }
                  >
                    {Math.round(student.average_score * 100)}
                  </span>
                ) : (
                  <span className="chip chip--neutral">—</span>
                )}
              </td>
              <td>{student.overdue}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
