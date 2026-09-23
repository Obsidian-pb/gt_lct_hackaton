import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api/client';
import type { Mistake, PersonalProgress, Work } from '../api/types';

const MODE_NAMES: Record<string, string> = {
  dispatcher: 'Диспетчер ДДС',
  operator: 'Оператор 112',
};

function percent(value: number): string {
  return `${Math.round(value * 100)}`;
}

/** Направление динамики: словами, а не только числом. */
function Trend({ value }: { value: number | null }) {
  if (value === null) {
    return (
      <div className="stat">
        <div className="stat__value">—</div>
        <div className="stat__label">
          Динамика появится после шести завершённых работ
        </div>
      </div>
    );
  }
  const points = Math.round(value * 100);
  const grew = points > 0;
  const flat = points === 0;
  return (
    <div className="stat">
      <div className={`stat__value${grew ? ' stat__value--ok' : flat ? '' : ' stat__value--bad'}`}>
        {grew ? '+' : ''}
        {points}
      </div>
      <div className="stat__label">
        {flat
          ? 'Результат держится на одном уровне'
          : grew
            ? 'Баллов прибавилось ко второй половине работ'
            : 'Баллов убавилось ко второй половине работ'}
      </div>
    </div>
  );
}

function MistakeRow({ mistake }: { mistake: Mistake }) {
  return (
    <div className={`violation violation--${mistake.severity}`}>
      <div className="violation__head">
        <span className="violation__code">{mistake.code}</span>
        <span className="violation__title">{mistake.title}</span>
        <span className="chip chip--neutral">{mistake.severity}</span>
        <div className="app-header__spacer" />
        <span className="card__meta">
          {mistake.count} раз · {percent(mistake.share)}% работ
        </span>
      </div>
      <div className="violation__example">
        <b>Почему это важно:</b> {mistake.example}
      </div>
    </div>
  );
}

function WorkRow({ work }: { work: Work }) {
  const score = Math.round(work.score * 100);
  const link = work.mode === 'operator' ? `/calls/${work.attempt_id}` : `/cards/${work.attempt_id}`;
  return (
    <tr>
      <td>
        <Link to={link}>{work.title}</Link>
        {work.is_repeat && (
          <>
            {' '}
            <span className="chip chip--warn">повторная выдача</span>{' '}
            <span className={work.repeat_fixed ? 'chip chip--ok' : 'chip chip--danger'}>
              {work.repeat_fixed ? 'исправлено' : 'не исправлено'}
            </span>
          </>
        )}
        {work.teacher_feedback && (
          <div className="advice">
            {work.teacher_feedback_by ?? 'Преподаватель'}: {work.teacher_feedback}
          </div>
        )}
      </td>
      <td className="card__meta">{MODE_NAMES[work.mode] ?? work.mode}</td>
      <td className="card__meta">
        {new Date(work.finished_at).toLocaleString('ru-RU', {
          day: '2-digit',
          month: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
        })}
      </td>
      <td>
        <span className={`chip ${score >= 80 ? 'chip--ok' : score >= 50 ? 'chip--neutral' : 'chip--danger'}`}>
          {score}
        </span>
      </td>
      <td className="card__meta">
        {work.violations === 0
          ? 'без замечаний'
          : `${work.violations} замеч.${work.critical ? `, из них критических ${work.critical}` : ''}`}
      </td>
    </tr>
  );
}

export function StudentProgressPage() {
  const [data, setData] = useState<PersonalProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .progress()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Не удалось загрузить прогресс'));
  }, []);

  if (error) return <div className="alert">{error}</div>;
  if (!data) return <div className="empty">Загрузка результатов…</div>;

  return (
    <>
      <div className="card">
        <div className="card__block">
          <h1 className="card__type">Мои результаты</h1>
          <div className="card__meta">{data.student_name}</div>

          <div className="stats">
            <div className="stat">
              <div className="stat__value">{percent(data.average_score)}</div>
              <div className="stat__label">
                Средний балл из 100
                {data.repeats_finished > 0 && ' · по первым попыткам'}
              </div>
            </div>
            <div className="stat">
              <div className="stat__value">
                {data.finished}
                <span className="stat__of"> из {data.total}</span>
              </div>
              <div className="stat__label">Работ завершено</div>
            </div>
            <div className="stat">
              <div className="stat__value">
                {data.average_pickup_seconds === null
                  ? '—'
                  : `${data.average_pickup_seconds} с`}
              </div>
              <div className="stat__label">Среднее время до взятия в работу</div>
            </div>
            <div className="stat">
              <div className={`stat__value${data.overdue_pickup ? ' stat__value--bad' : ''}`}>
                {data.overdue_pickup}
              </div>
              <div className="stat__label">Опозданий с взятием в работу</div>
            </div>
            <Trend value={data.trend} />
          </div>
        </div>
      </div>

      {data.by_mode.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card__block">
            <div className="card__label">По режимам обучения</div>
            <table className="card-table">
              <thead>
                <tr>
                  <th>Режим</th>
                  <th>Завершено</th>
                  <th>Средний балл</th>
                  <th>Опозданий</th>
                </tr>
              </thead>
              <tbody>
                {data.by_mode.map((mode) => (
                  <tr key={mode.mode}>
                    <td>{MODE_NAMES[mode.mode] ?? mode.mode}</td>
                    <td>
                      {mode.finished} из {mode.attempts}
                    </td>
                    <td>{percent(mode.average_score)}</td>
                    <td>{mode.overdue_pickup}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card__block">
          <div className="card__label">Что стоит отработать</div>
          {data.advice.map((line, index) => (
            <p key={index} className="advice">
              {line}
            </p>
          ))}
        </div>
      </div>

      {data.mistakes.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card__block">
            <div className="card__label">
              История ошибок — сначала те, что тяжелее по последствиям
            </div>
            {data.mistakes.map((mistake) => (
              <MistakeRow key={mistake.code} mistake={mistake} />
            ))}
          </div>
        </div>
      )}

      {data.works.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card__block">
            <div className="card__label">
              Завершённые работы
              {data.works.some((w) => w.teacher_feedback) &&
                ' — преподаватель прокомментировал часть из них'}
            </div>
            <table className="card-table">
              <thead>
                <tr>
                  <th>Сценарий</th>
                  <th>Режим</th>
                  <th>Завершено</th>
                  <th>Балл</th>
                  <th>Замечания</th>
                </tr>
              </thead>
              <tbody>
                {data.works.map((work) => (
                  <WorkRow key={work.attempt_id} work={work} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {data.grammar_issues > 0 && (
        <p className="page-hint">
          Замечаний к грамматике во внесённых текстах: {data.grammar_issues}. Они
          перечислены в разборе каждой работы.
        </p>
      )}
    </>
  );
}
