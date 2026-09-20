import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api, teacherApi } from '../api/client';
import type { TrainingSession } from '../api/types';

export const STATE_LABELS: Record<string, string> = {
  draft: 'черновик',
  active: 'идёт',
  finished: 'завершено',
};

export const MODE_LABELS: Record<string, string> = {
  dispatcher: 'диспетчер ДДС',
  operator: 'оператор 112',
};

function stateChip(state: string): string {
  if (state === 'active') return 'chip chip--ok';
  if (state === 'finished') return 'chip chip--neutral';
  return 'chip chip--warn';
}

function CreateForm({ onCreated }: { onCreated: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [mode, setMode] = useState('dispatcher');
  const [interval, setIntervalSeconds] = useState(20);
  const [pickup, setPickup] = useState(30);
  const [handling, setHandling] = useState(180);
  // Критерии успешности: на экране балл стобалльный, на сервер уходит доля.
  const [passScore, setPassScore] = useState(70);
  const [maxCritical, setMaxCritical] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const session = await teacherApi.createSession({
        title,
        mode,
        pickup_deadline_seconds: pickup,
        handling_deadline_seconds: handling,
        call_interval_seconds: interval,
        pass_score: passScore / 100,
        max_critical_violations: maxCritical,
      });
      onCreated(session.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось создать занятие');
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="actions" style={{ marginBottom: 16 }}>
        <button className="btn" onClick={() => setOpen(true)}>
          Создать занятие
        </button>
      </div>
    );
  }

  return (
    <div className="panel-form">
      <div className="field">
        <label htmlFor="title">Название занятия</label>
        <input
          id="title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Например: отработка отказов от непрофильных вызовов"
          autoFocus
        />
      </div>
      <div className="field">
        <label htmlFor="mode">Кого обучаем</label>
        <select id="mode" value={mode} onChange={(e) => setMode(e.target.value)}>
          {Object.entries(MODE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field field--narrow">
        <label htmlFor="interval">Интервал вызовов, с</label>
        <input
          id="interval"
          type="number"
          min={0}
          max={600}
          value={interval}
          onChange={(e) => setIntervalSeconds(Number(e.target.value))}
        />
      </div>
      <div className="field field--narrow">
        <label htmlFor="pickup">Взять в работу, с</label>
        <input
          id="pickup"
          type="number"
          min={5}
          max={300}
          value={pickup}
          onChange={(e) => setPickup(Number(e.target.value))}
        />
      </div>
      <div className="field field--narrow">
        <label htmlFor="handling">Обработка, с</label>
        <input
          id="handling"
          type="number"
          min={30}
          max={1800}
          value={handling}
          onChange={(e) => setHandling(Number(e.target.value))}
        />
      </div>
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
      <button className="btn" onClick={submit} disabled={busy || title.trim().length < 3}>
        Создать
      </button>
      <button className="btn btn--ghost" onClick={() => setOpen(false)}>
        Отмена
      </button>
      <p className="page-hint" style={{ width: '100%', margin: 0 }}>
        Чем меньше интервал между вызовами, тем больше карточек висит на обучающемся
        одновременно. Это основной регулятор нагрузки: занятие с интервалом в пять секунд
        заведомо не позволяет успеть всё и проверяет умение расставлять приоритеты.
      </p>
      <p className="page-hint" style={{ width: '100%', margin: 0 }}>
        Занятие зачтено, если средний балл не ниже порога и критических нарушений
        не больше допустимого. Критическое нарушение — то, из-за которого служба
        не выехала бы на происшествие, поэтому по умолчанию их не прощают вовсе.
      </p>
      {error && <div className="alert" style={{ width: '100%' }}>{error}</div>}
    </div>
  );
}

export function TeacherSessionsPage() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<TrainingSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setSessions(await api.sessions());
  }, []);

  useEffect(() => {
    reload().catch((e) =>
      setError(e instanceof Error ? e.message : 'Не удалось загрузить занятия'),
    );
  }, [reload]);

  if (error) return <div className="alert">{error}</div>;
  if (!sessions) return <div className="empty">Загрузка…</div>;

  return (
    <>
      <h1 className="page-title">Занятия</h1>
      <p className="page-hint">
        Занятие связывает утверждённые сценарии с обучающимися. После запуска вызовы
        поступают потоком, а вы видите ход занятия в реальном времени.
      </p>

      <CreateForm onCreated={(id) => navigate(`/sessions/${id}`)} />

      {sessions.length === 0 ? (
        <div className="empty">Занятий пока нет.</div>
      ) : (
        <table className="card-table">
          <thead>
            <tr>
              <th style={{ width: '45%' }}>Занятие</th>
              <th>Состав</th>
              <th>Поток</th>
              <th>Состояние</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((session) => (
              <tr key={session.id} onClick={() => navigate(`/sessions/${session.id}`)}>
                <td>
                  <div className="card-table__type">{session.title}</div>
                  <div className="card-table__address">
                    {MODE_LABELS[session.mode] ?? session.mode}
                  </div>
                </td>
                <td className="card-table__address">
                  {session.students.length} обучающихся · {session.approved_scenarios} карточек
                </td>
                <td className="card-table__address">
                  вызов раз в {session.call_interval_seconds} с
                </td>
                <td>
                  <span className={stateChip(session.state)}>
                    {STATE_LABELS[session.state] ?? session.state}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
