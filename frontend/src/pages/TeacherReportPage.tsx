import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api, teacherApi } from '../api/client';
import type { Report, SessionWork, TrainingSession } from '../api/types';
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

/**
 * Одна работа с полем для примечания преподавателя. Экспортируется:
 * сквозной список работ показывает ту же форму, а не свою копию.
 */
export function WorkFeedback({
  work,
  onSaved,
}: {
  work: SessionWork;
  onSaved: (work: SessionWork) => void;
}) {
  const [text, setText] = useState(work.teacher_feedback ?? '');
  // Итоговый балл — строкой: поле может быть пустым, это «итог = машинный».
  const initialFinal = work.final_score != null ? String(Math.round(work.final_score * 100)) : '';
  const [finalText, setFinalText] = useState(initialFinal);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const finalValue = finalText.trim() === '' ? null : Number(finalText);
  const finalInvalid =
    finalValue !== null && (!Number.isFinite(finalValue) || finalValue < 0 || finalValue > 100);
  const finalChanged = finalText.trim() !== initialFinal;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      onSaved(
        await teacherApi.leaveFeedback(
          work.attempt_id,
          text.trim(),
          // Балл уходит, только если его правили: примечание без правки
          // итог не трогает.
          finalChanged ? (finalValue === null ? null : finalValue / 100) : undefined,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить примечание');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="draft">
      <div className="draft__head">
        <div>
          <div className="draft__type">{work.student_name}</div>
          <div className="card__meta">{work.scenario_title}</div>
        </div>
        <div className="draft__badges">
          {work.score === null ? (
            <span className="chip chip--neutral">не завершена</span>
          ) : (
            <span className={work.score >= 0.7 ? 'chip chip--ok' : 'chip chip--danger'}>
              {Math.round(work.score * 100)} баллов
            </span>
          )}
          {work.final_score != null && work.machine_score != null && (
            <span
              className="chip chip--neutral"
              title={`Итог подтвердил ${work.final_score_by ?? 'преподаватель'}`}
            >
              машинный {Math.round(work.machine_score * 100)} → итоговый{' '}
              {Math.round(work.final_score * 100)}
            </span>
          )}
          {work.critical > 0 && (
            <span className="chip chip--danger">критических: {work.critical}</span>
          )}
          {work.repeat_of_id !== null && (
            <span className="chip chip--warn" title={`Повтор работы № ${work.repeat_of_id}`}>
              повторная выдача
            </span>
          )}
        </div>
      </div>

      {work.teacher_feedback_at && (
        <div className="draft__note">
          Примечание оставил {work.teacher_feedback_by ?? 'преподаватель'},{' '}
          {new Date(work.teacher_feedback_at).toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
          })}
        </div>
      )}

      <textarea
        className="comment-area"
        style={{ marginTop: 10 }}
        placeholder="Что сказать обучающемуся по этой работе? Примечание увидит он один."
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {work.score !== null && (
        <div className="field final-score">
          <label htmlFor={`final-${work.attempt_id}`}>
            Итоговый балл{' '}
            <span className="card__meta">
              · пусто — равен машинному ({Math.round((work.machine_score ?? work.score) * 100)}); при
              изменении обоснуйте в примечании
            </span>
          </label>
          <input
            id={`final-${work.attempt_id}`}
            inputMode="numeric"
            value={finalText}
            placeholder="0–100"
            onChange={(e) => setFinalText(e.target.value)}
          />
          {finalInvalid && <span className="card__meta">от 0 до 100</span>}
        </div>
      )}
      <div className="actions">
        <button
          className="btn btn--ghost"
          disabled={busy || text.trim().length < 3 || finalInvalid}
          onClick={save}
        >
          {finalChanged
            ? 'Сохранить примечание и итоговый балл'
            : work.teacher_feedback
              ? 'Изменить примечание'
              : 'Оставить примечание'}
        </button>
      </div>
      {error && <div className="alert">{error}</div>}
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
  const [works, setWorks] = useState<SessionWork[]>([]);
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
    teacherApi.sessionWorks(sessionId).then(setWorks).catch(() => undefined);
  }, [sessionId]);

  // Сохранённое примечание подменяем в списке, а не перезагружаем отчёт:
  // иначе набранный в соседних полях текст пропал бы.
  const replaceWork = useCallback((saved: SessionWork) => {
    setWorks((current) =>
      current.map((w) => (w.attempt_id === saved.attempt_id ? saved : w)),
    );
  }, []);

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
        <Stat
          label="Прошли порог"
          value={`${report.passed_students} / ${report.passed_students + report.failed_students}`}
          hint={`зачёт от ${Math.round(report.pass_score * 100)} баллов при ${
            report.max_critical_violations
          } критических`}
        />
        {report.repeats_issued > 0 && (
          <Stat
            label="Повторных выдач"
            value={String(report.repeats_issued)}
            hint={
              report.repeats_finished
                ? `исправились ${report.repeats_fixed} из ${report.repeats_finished}`
                : 'ещё не завершены'
            }
          />
        )}
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
      {report.repeats_issued > 0 && (
        <p className="page-hint">
          Средний балл и зачёт считаются по первым попыткам. Повторные выдачи
          проваленных карточек показаны под именем: балл первой попытки, балл
          после повтора и исправился ли обучающийся.
        </p>
      )}
      <table className="card-table">
        <thead>
          <tr>
            <th>Обучающийся</th>
            <th>Карточек</th>
            <th>Завершено</th>
            <th>Средний балл</th>
            <th>Просрочек</th>
            <th>Критических</th>
            <th>Зачёт</th>
          </tr>
        </thead>
        <tbody>
          {report.students.map((student) => (
            <tr key={student.student_id}>
              <td>
                {student.student_name}
                {student.repeats.length > 0 && (
                  <ul className="repeat-list">
                    {student.repeats.map((repeat) => (
                      <li key={repeat.repeat_attempt_id}>
                        повтор «{repeat.scenario_title}»:{' '}
                        {repeat.first_score !== null ? Math.round(repeat.first_score * 100) : '—'}
                        {' → '}
                        {repeat.repeat_score !== null
                          ? Math.round(repeat.repeat_score * 100)
                          : '—'}
                        {' · '}
                        {repeat.fixed === null ? (
                          <span className="chip chip--neutral">не завершён</span>
                        ) : (
                          <span className={repeat.fixed ? 'chip chip--ok' : 'chip chip--danger'}>
                            {repeat.fixed ? 'исправился' : 'не исправился'}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </td>
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
              <td>{student.critical}</td>
              <td>
                {student.passed === null ? (
                  <span className="chip chip--neutral">нет работ</span>
                ) : (
                  <span className={student.passed ? 'chip chip--ok' : 'chip chip--danger'}>
                    {student.passed ? 'зачтено' : 'не зачтено'}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="section-heading">Обратная связь по работам</h2>
      <p className="page-hint">
        Автоматический разбор говорит, что нарушено, но не говорит, что делать
        обучающемуся дальше. Примечание к работе он увидит в разборе карточки
        и в своём личном кабинете; автор и время сохраняются в журнале аудита.
      </p>
      {works.length === 0 ? (
        <div className="empty">Работ по этому занятию пока нет.</div>
      ) : (
        works.map((work) => (
          <WorkFeedback key={work.attempt_id} work={work} onSaved={replaceWork} />
        ))
      )}
    </>
  );
}
