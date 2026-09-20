import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { api, teacherApi } from '../api/client';
import type { Scenario, SessionMember, SessionMonitor, TrainingSession } from '../api/types';
import { MODE_LABELS, STATE_LABELS } from './TeacherSessionsPage';

const DIFFICULTY_LABELS: Record<number, string> = {
  1: 'простые',
  2: 'средние',
  3: 'сложные',
};

/** Критерии успешности занятия — правятся, пока занятие в черновике. */
function Criteria({ session, onChanged }: { session: TrainingSession; onChanged: () => void }) {
  const [passScore, setPassScore] = useState(Math.round(session.pass_score * 100));
  const [maxCritical, setMaxCritical] = useState(session.max_critical_violations);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    setError(null);
    setSaved(false);
    try {
      await api.updateSession(session.id, {
        pass_score: passScore / 100,
        max_critical_violations: maxCritical,
      });
      setSaved(true);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось изменить критерии');
    }
  }

  return (
    <>
      <h2 className="section-heading">Критерии успешности</h2>
      <p className="page-hint">
        Работа зачтена, если средний балл не ниже порога и критических нарушений
        не больше допустимого. В отчёте по каждому обучающемуся будет видно, прошёл
        он порог или нет.
      </p>
      <div className="panel-form">
        <div className="field field--narrow">
          <label htmlFor="pass-score">Порог зачёта, баллов</label>
          <input
            id="pass-score"
            type="number"
            min={0}
            max={100}
            value={passScore}
            onChange={(e) => setPassScore(Number(e.target.value))}
          />
        </div>
        <div className="field field--narrow">
          <label htmlFor="max-critical">Критических нарушений</label>
          <input
            id="max-critical"
            type="number"
            min={0}
            max={100}
            value={maxCritical}
            onChange={(e) => setMaxCritical(Number(e.target.value))}
          />
        </div>
        <button className="btn btn--ghost" onClick={save}>
          Сохранить критерии
        </button>
      </div>
      {error && <div className="alert">{error}</div>}
      {saved && !error && <div className="pending">Критерии сохранены.</div>}
    </>
  );
}

/** Набор состава — доступен только до запуска занятия. */
function Compose({
  session,
  onChanged,
}: {
  session: TrainingSession;
  onChanged: () => void;
}) {
  const [students, setStudents] = useState<SessionMember[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [difficulty, setDifficulty] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const chosenStudents = new Set(session.students.map((s) => s.id));
  const chosenScenarios = new Set(session.scenarios.map((s) => s.id));

  useEffect(() => {
    api.sessionStudents().then(setStudents).catch(() => undefined);
  }, []);

  useEffect(() => {
    // Только утверждённые и только своего режима: чужие в ленту не попадут.
    // Уровень сложности отбирает сервер: показывать выбранный уровень, но
    // держать в памяти весь список — значит рано или поздно разойтись с ним.
    teacherApi
      .scenariosByDifficulty(true, session.mode, difficulty)
      .then(setScenarios)
      .catch(() => undefined);
  }, [session.mode, difficulty]);

  async function toggle(kind: 'student_ids' | 'scenario_ids', id: number) {
    const current = kind === 'student_ids' ? chosenStudents : chosenScenarios;
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    try {
      await api.updateSession(session.id, { [kind]: [...next] });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось изменить состав');
    }
  }

  return (
    <>
      {error && <div className="alert">{error}</div>}

      <h2 className="section-heading">Обучающиеся</h2>
      {students.length === 0 ? (
        <div className="empty">Нет доступных обучающихся.</div>
      ) : (
        <div className="picker">
          {students.map((student) => (
            <button
              key={student.id}
              type="button"
              className={`picker__item${chosenStudents.has(student.id) ? ' picker__item--on' : ''}`}
              onClick={() => toggle('student_ids', student.id)}
            >
              <span>{student.full_name}</span>
              <span className="picker__hint">{student.service ?? 'без службы'}</span>
            </button>
          ))}
        </div>
      )}

      <h2 className="section-heading">Карточки занятия</h2>
      <p className="page-hint">
        Доступны только утверждённые сценарии режима «{MODE_LABELS[session.mode]}». Каждый
        обучающийся получит их все, но в своём порядке — от простых к сложным.
      </p>

      <div className="field field--narrow">
        <label htmlFor="difficulty-filter">Уровень сложности</label>
        <select
          id="difficulty-filter"
          value={difficulty ?? ''}
          onChange={(e) => setDifficulty(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">все уровни</option>
          {Object.entries(DIFFICULTY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {scenarios.length === 0 ? (
        <div className="empty">
          {difficulty === null
            ? 'Утверждённых сценариев этого режима нет. Сформируйте и утвердите их на вкладке «Сценарии».'
            : `Утверждённых сценариев уровня «${DIFFICULTY_LABELS[difficulty]}» нет. Выберите другой уровень или сформируйте карточки на вкладке «Сценарии».`}
        </div>
      ) : (
        <div className="picker">
          {scenarios.map((scenario) => (
            <button
              key={scenario.id}
              type="button"
              className={`picker__item${chosenScenarios.has(scenario.id) ? ' picker__item--on' : ''}`}
              onClick={() => toggle('scenario_ids', scenario.id)}
            >
              <span>{scenario.incident_type || scenario.title}</span>
              <span className="picker__hint">
                {DIFFICULTY_LABELS[scenario.difficulty] ?? scenario.difficulty} ·{' '}
                {scenario.is_profile ? 'профильное' : 'непрофильное'}
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

/** Ход занятия в реальном времени. */
function Monitor({ sessionId, interval }: { sessionId: number; interval: number }) {
  const [data, setData] = useState<SessionMonitor | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    const load = () => api.monitorSession(sessionId).then(setData).catch(() => undefined);
    load();
    // Вызовы приходят по расписанию, поэтому картина меняется сама по себе —
    // опрашиваем её чаще, чем интервал между вызовами.
    timer.current = window.setInterval(load, Math.max(2000, interval * 400));
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [sessionId, interval]);

  if (!data) return <div className="empty">Загрузка хода занятия…</div>;

  return (
    <>
      <div className="stats">
        <div className="stat">
          <div className="stat__value">
            {data.issued}
            <span style={{ fontSize: 15, color: 'var(--muted)' }}> / {data.total_planned}</span>
          </div>
          <div className="stat__label">Вызовов поступило</div>
          <div className="stat__hint">раз в {data.call_interval_seconds} с</div>
        </div>
        <div className="stat">
          <div className="stat__value">{data.finished}</div>
          <div className="stat__label">Карточек обработано</div>
        </div>
        <div className="stat">
          <div className="stat__value">
            {data.students.reduce((sum, s) => sum + s.in_work, 0)}
          </div>
          <div className="stat__label">Сейчас в работе</div>
        </div>
        <div className="stat">
          <div className="stat__value" style={{ color: 'var(--danger)' }}>
            {data.students.reduce((sum, s) => sum + s.overdue_pickup, 0)}
          </div>
          <div className="stat__label">Просрочено взятие</div>
          <div className="stat__hint">норматив {data.pickup_deadline_seconds} с</div>
        </div>
      </div>

      <table className="card-table">
        <thead>
          <tr>
            <th>Обучающийся</th>
            <th>Поступило</th>
            <th>Взято в работу</th>
            <th>В работе сейчас</th>
            <th>Обработано</th>
            <th>Просрочено</th>
          </tr>
        </thead>
        <tbody>
          {data.students.map((row) => (
            <tr key={row.student_id} style={{ cursor: 'default' }}>
              <td className="card-table__type">{row.student_name}</td>
              <td>{row.issued}</td>
              <td>{row.opened}</td>
              <td>
                <span className={row.in_work > 3 ? 'chip chip--warn' : 'chip chip--neutral'}>
                  {row.in_work}
                </span>
              </td>
              <td>{row.finished}</td>
              <td>
                <span
                  className={row.overdue_pickup > 0 ? 'chip chip--danger' : 'chip chip--ok'}
                >
                  {row.overdue_pickup}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function TeacherSessionPage() {
  const { id } = useParams();
  const sessionId = Number(id);
  const navigate = useNavigate();

  const [session, setSession] = useState<TrainingSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const all = await api.sessions();
    const found = all.find((s) => s.id === sessionId) ?? null;
    setSession(found);
  }, [sessionId]);

  useEffect(() => {
    reload().catch((e) => setError(e instanceof Error ? e.message : 'Занятие недоступно'));
  }, [reload]);

  async function act(action: () => Promise<TrainingSession>) {
    setBusy(true);
    setError(null);
    try {
      setSession(await action());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Операция не выполнена');
    } finally {
      setBusy(false);
    }
  }

  if (error && !session) return <div className="alert">{error}</div>;
  if (!session) return <div className="empty">Загрузка занятия…</div>;

  const draft = session.state === 'draft';
  const active = session.state === 'active';
  const canStart = session.students.length > 0 && session.approved_scenarios > 0;

  return (
    <>
      <p className="page-hint">
        <Link to="/sessions">← Ко всем занятиям</Link>
      </p>

      <h1 className="page-title">{session.title}</h1>
      <p className="page-hint">
        {MODE_LABELS[session.mode] ?? session.mode} ·{' '}
        <span className="chip chip--neutral">
          {STATE_LABELS[session.state] ?? session.state}
        </span>{' '}
        · вызов раз в {session.call_interval_seconds} с · взять в работу за{' '}
        {session.pickup_deadline_seconds} с · обработать за{' '}
        {session.handling_deadline_seconds} с · зачёт от{' '}
        {Math.round(session.pass_score * 100)} баллов при{' '}
        {session.max_critical_violations} критических нарушениях
      </p>

      {error && <div className="alert">{error}</div>}

      {draft && (
        <>
          <Criteria session={session} onChanged={() => reload().catch(() => undefined)} />
          <Compose session={session} onChanged={() => reload().catch(() => undefined)} />
        </>
      )}
      {active && (
        <Monitor sessionId={session.id} interval={session.call_interval_seconds} />
      )}
      {session.state === 'finished' && (
        <div className="empty">
          Занятие завершено. <Link to={`/report?session=${session.id}`}>Открыть отчёт</Link>
        </div>
      )}

      <div className="actions">
        {draft && (
          <button
            className="btn"
            disabled={busy || !canStart}
            onClick={() => act(() => api.startSession(session.id))}
            title={
              canStart
                ? undefined
                : 'Нужен хотя бы один обучающийся и одна утверждённая карточка'
            }
          >
            Начать занятие
          </button>
        )}
        {active && (
          <button
            className="btn"
            disabled={busy}
            onClick={() =>
              act(async () => {
                const finished = await api.finishSession(session.id);
                navigate(`/report?session=${session.id}`);
                return finished;
              })
            }
          >
            Завершить занятие
          </button>
        )}
      </div>

      {draft && !canStart && (
        <p className="page-hint">
          Чтобы начать, включите в занятие хотя бы одного обучающегося и одну утверждённую
          карточку.
        </p>
      )}
    </>
  );
}
