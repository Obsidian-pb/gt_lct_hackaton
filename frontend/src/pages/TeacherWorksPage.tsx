import { Fragment, useCallback, useEffect, useState } from 'react';

import { api, teacherApi } from '../api/client';
import type { Evaluation, SessionWork, WorksFilters, WorksQuery } from '../api/types';
import { EvaluationReport } from '../components/EvaluationReport';
import { WorkFeedback } from './TeacherReportPage';

const PAGE = 50;

const MODE_NAMES: Record<string, string> = {
  dispatcher: 'Диспетчер ДДС',
  operator: 'Оператор 112',
};

/** Значения полей формы: строки, как их отдаёт разметка; в запрос — через toQuery. */
interface Draft {
  student_id: string;
  session_id: string;
  mode: string;
  date_from: string;
  date_to: string;
  passed: '' | 'true' | 'false';
  q: string;
}

const EMPTY: Draft = {
  student_id: '',
  session_id: '',
  mode: '',
  date_from: '',
  date_to: '',
  passed: '',
  q: '',
};

function toQuery(draft: Draft): WorksQuery {
  return {
    student_id: draft.student_id ? Number(draft.student_id) : undefined,
    session_id: draft.session_id ? Number(draft.session_id) : undefined,
    mode: draft.mode || undefined,
    date_from: draft.date_from || undefined,
    date_to: draft.date_to || undefined,
    passed: draft.passed === '' ? undefined : draft.passed === 'true',
    q: draft.q.trim() || undefined,
  };
}

function formatDate(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Раскрытая строка: разбор работы тем же компонентом, что видит обучающийся,
 * и форма примечания из отчёта занятия. Разбор подгружается по щелчку,
 * а не вместе со списком: в нём весь перечень нарушений с цитатами,
 * и тянуть его для полусотни строк ради одной открытой — расточительно.
 */
function WorkDetails({
  work,
  onSaved,
}: {
  work: SessionWork;
  onSaved: (work: SessionWork) => void;
}) {
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .evaluation(work.attempt_id)
      .then(setEvaluation)
      .catch((e) => setError(e instanceof Error ? e.message : 'Не удалось загрузить разбор'));
  }, [work.attempt_id]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      {evaluation ? (
        <EvaluationReport evaluation={evaluation} />
      ) : error ? (
        <div className="alert">{error}</div>
      ) : (
        <div className="empty">Загрузка разбора…</div>
      )}
      {/* После сохранения примечания разбор перечитывается: он показывает
          примечание сверху, и старый текст там сбивал бы с толку. */}
      <WorkFeedback
        work={work}
        onSaved={(saved) => {
          onSaved(saved);
          load();
        }}
      />
    </>
  );
}

export function TeacherWorksPage() {
  const [filters, setFilters] = useState<WorksFilters | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  // Условия применяются кнопкой, а не на каждое нажатие: поиск по словам
  // и период набираются в несколько действий, и дёргать список на каждое —
  // значит показывать преподавателю мельтешащие промежуточные результаты.
  const [applied, setApplied] = useState<WorksQuery>({});
  const [items, setItems] = useState<SessionWork[]>([]);
  const [total, setTotal] = useState(0);
  // Признак загрузки взводится там, где запрос затевается — в обработчиках
  // и при первом показе, — а не внутри эффекта: синхронный setState в эффекте
  // даёт лишний каскад отрисовок, и линтер проекта на него жалуется.
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

  useEffect(() => {
    teacherApi.worksFilters().then(setFilters).catch(() => undefined);
  }, []);

  const load = useCallback(async (query: WorksQuery, offset: number) => {
    try {
      const page = await teacherApi.works({ ...query, limit: PAGE, offset });
      setItems((current) => (offset === 0 ? page.items : [...current, ...page.items]));
      setTotal(page.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить работы');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(applied, 0);
  }, [applied, load]);

  function apply() {
    setOpenId(null);
    setError(null);
    setLoading(true);
    setApplied(toQuery(draft));
  }

  function reset() {
    setDraft(EMPTY);
    setOpenId(null);
    setError(null);
    setLoading(true);
    setApplied({});
  }

  function more() {
    setError(null);
    setLoading(true);
    load(applied, items.length);
  }

  // Сохранённое примечание подменяем в строке, как в отчёте: перезагрузка
  // списка закрыла бы раскрытую работу и сбила бы прокрутку.
  const replaceWork = useCallback((saved: SessionWork) => {
    setItems((current) => current.map((w) => (w.attempt_id === saved.attempt_id ? saved : w)));
  }, []);

  function update<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  return (
    <>
      <h1 className="page-title">Работы обучающихся</h1>
      <p className="page-hint">
        Все завершённые карточки по всем занятиям, новые сверху. Строка раскрывается
        в разбор работы; примечание к ней обучающийся увидит в карточке и в своём кабинете.
      </p>

      <form
        className="panel-form works-filters"
        onSubmit={(e) => {
          e.preventDefault();
          apply();
        }}
      >
        <div className="field">
          <label htmlFor="works-student">Обучающийся</label>
          <select
            id="works-student"
            value={draft.student_id}
            onChange={(e) => update('student_id', e.target.value)}
          >
            <option value="">все</option>
            {filters?.students.map((s) => (
              <option key={s.id} value={s.id}>
                {s.full_name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="works-session">Занятие</label>
          <select
            id="works-session"
            value={draft.session_id}
            onChange={(e) => update('session_id', e.target.value)}
          >
            <option value="">все</option>
            {filters?.sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title} — {MODE_NAMES[s.mode] ?? s.mode}
              </option>
            ))}
          </select>
        </div>
        <div className="field field--narrow">
          <label htmlFor="works-mode">Режим</label>
          <select id="works-mode" value={draft.mode} onChange={(e) => update('mode', e.target.value)}>
            <option value="">любой</option>
            <option value="dispatcher">{MODE_NAMES.dispatcher}</option>
            <option value="operator">{MODE_NAMES.operator}</option>
          </select>
        </div>
        <div className="field field--date">
          <label htmlFor="works-from">С</label>
          <input
            id="works-from"
            type="date"
            value={draft.date_from}
            max={draft.date_to || undefined}
            onChange={(e) => update('date_from', e.target.value)}
          />
        </div>
        <div className="field field--date">
          <label htmlFor="works-to">По</label>
          <input
            id="works-to"
            type="date"
            value={draft.date_to}
            min={draft.date_from || undefined}
            onChange={(e) => update('date_to', e.target.value)}
          />
        </div>
        <div className="field field--narrow">
          <label htmlFor="works-passed">Зачёт</label>
          <select
            id="works-passed"
            value={draft.passed}
            onChange={(e) => update('passed', e.target.value as Draft['passed'])}
          >
            <option value="">все</option>
            <option value="true">зачтены</option>
            <option value="false">не зачтены</option>
          </select>
        </div>
        <div className="field field--search">
          <label htmlFor="works-q">Поиск</label>
          <input
            id="works-q"
            type="search"
            placeholder="сценарий, тип происшествия, адрес"
            value={draft.q}
            onChange={(e) => update('q', e.target.value)}
          />
        </div>
        <div className="actions" style={{ marginTop: 0 }}>
          <button className="btn" type="submit" disabled={loading}>
            Применить
          </button>
          <button className="btn btn--ghost" type="button" disabled={loading} onClick={reset}>
            Сбросить
          </button>
        </div>
      </form>

      {error && <div className="alert">{error}</div>}

      <div className="works-count">
        {loading && items.length === 0 ? 'Загрузка…' : `найдено ${total}`}
      </div>

      {!loading && items.length === 0 && !error ? (
        <div className="empty">Работ по таким условиям нет.</div>
      ) : (
        <table className="card-table works-table">
          <thead>
            <tr>
              <th>Дата</th>
              <th>Обучающийся</th>
              <th>Занятие</th>
              <th>Режим</th>
              <th>Сценарий</th>
              <th>Балл</th>
              <th>Нарушений</th>
              <th>Зачёт</th>
              <th>Примечание</th>
            </tr>
          </thead>
          <tbody>
            {items.map((work) => {
              const open = openId === work.attempt_id;
              return (
                <Fragment key={work.attempt_id}>
                  <tr
                    className={open ? 'works-row--open' : undefined}
                    onClick={() => setOpenId(open ? null : work.attempt_id)}
                  >
                    <td>{formatDate(work.finished_at)}</td>
                    <td className="works-cell--wrap">{work.student_name}</td>
                    <td className="works-cell--wrap">{work.session_title}</td>
                    <td>{MODE_NAMES[work.mode] ?? work.mode}</td>
                    <td className="works-cell--wrap">
                      {work.scenario_title}
                      {work.repeat_of_id !== null && (
                        <>
                          {' '}
                          <span
                            className="chip chip--warn"
                            title={`Повтор работы № ${work.repeat_of_id}`}
                          >
                            повтор
                          </span>
                        </>
                      )}
                    </td>
                    <td>{work.score === null ? '—' : Math.round(work.score * 100)}</td>
                    <td>
                      {work.violations}
                      {work.critical > 0 && (
                        <span className="works-critical" title="из них критических">
                          {' '}
                          · {work.critical} крит.
                        </span>
                      )}
                    </td>
                    <td>
                      {work.passed === null ? (
                        <span className="chip chip--neutral">нет оценки</span>
                      ) : (
                        <span className={work.passed ? 'chip chip--ok' : 'chip chip--danger'}>
                          {work.passed ? 'зачтено' : 'не зачтено'}
                        </span>
                      )}
                    </td>
                    <td>
                      {work.teacher_feedback ? (
                        <span className="chip chip--ok" title={work.teacher_feedback}>
                          есть
                        </span>
                      ) : (
                        <span className="chip chip--neutral">нет</span>
                      )}
                    </td>
                  </tr>
                  {open && (
                    <tr className="works-details">
                      <td colSpan={9}>
                        <WorkDetails work={work} onSaved={replaceWork} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}

      {items.length < total && (
        <div className="works-more">
          <button className="btn btn--ghost" disabled={loading} onClick={more}>
            {loading ? 'Загрузка…' : `Показать ещё (${total - items.length})`}
          </button>
        </div>
      )}
    </>
  );
}
