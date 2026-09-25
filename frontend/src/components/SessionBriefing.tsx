import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api/client';
import type { StudentSessionBrief } from '../api/types';

/**
 * Занятие глазами обучающегося — до, во время и после.
 *
 * До первого вызова — инструктаж: что за занятие, нормативы, сколько
 * карточек и когда первая, что от него ждут. В реальной смене человек
 * знает, куда сел; в тренажёре без этого экрана первая карточка падает
 * на голову. Во время — короткая строка состояния. После последней —
 * итог: балл, критические, зачёт, и куда идти за разбором.
 *
 * Инструктаж показывается один раз на занятие и запоминается в браузере:
 * это удобство просмотра, а не данные, поэтому localStorage уместен.
 */
const MODE_TEXT = {
  operator: {
    role: 'оператор Службы 112',
    task:
      'Выслушать заявителя, решить, наше ли это происшествие, классифицировать его по опросной карте, отметить признаки, записать адрес по частям и телефон для связи.',
  },
  dispatcher: {
    role: 'диспетчер ДДС',
    task:
      'Принять карточку в течение норматива, проставлять статусы реагирования по ходу работ и сопровождать их комментариями с обязательными сведениями.',
  },
};

function seenKey(id: number) {
  return `dds112:briefing-seen:${id}`;
}

function readSeen(id: number): boolean {
  try {
    return localStorage.getItem(seenKey(id)) === '1';
  } catch {
    return false;
  }
}

export function SessionBriefing({ mode }: { mode: 'operator' | 'dispatcher' }) {
  const [sessions, setSessions] = useState<StudentSessionBrief[] | null>(null);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

  useEffect(() => {
    api
      .mySessions()
      .then(setSessions)
      .catch(() => setSessions([]));
  }, []);

  if (!sessions) return null;
  const session = sessions.find((s) => s.mode === mode && s.state === 'active')
    ?? sessions.find((s) => s.mode === mode);
  if (!session) return null;

  const text = MODE_TEXT[mode];
  const allDone = session.cards_total > 0 && session.cards_done === session.cards_total;
  const finished = session.state === 'finished' || allDone;
  const notStarted = session.cards_done === 0 && !finished;
  const showBriefing = notStarted && !readSeen(session.id) && !dismissed.has(session.id);

  const start = () => {
    try {
      localStorage.setItem(seenKey(session.id), '1');
    } catch {
      // Без хранилища инструктаж просто покажется ещё раз — это не ошибка.
    }
    setDismissed((current) => new Set(current).add(session.id));
  };

  if (finished) {
    const passed = session.passed;
    return (
      <div className={`briefing briefing--result${passed === false ? ' briefing--failed' : ''}`}>
        <div className="briefing__head">
          <div>
            <div className="card__label">Занятие завершено</div>
            <h2 className="briefing__title">{session.title}</h2>
          </div>
          {passed !== null && (
            <span className={`chip ${passed ? 'chip--ok' : 'chip--danger'}`}>
              {passed ? 'зачтено' : 'не зачтено'}
            </span>
          )}
        </div>
        <div className="briefing__stats">
          <div className="stat">
            <div className="stat__value">{Math.round(session.average_score * 100)}</div>
            <div className="stat__hint">средний балл · зачёт от {Math.round(session.pass_score * 100)}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{session.critical}</div>
            <div className="stat__hint">критических нарушений · допустимо {session.max_critical_violations}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{session.cards_done}</div>
            <div className="stat__hint">карточек обработано</div>
          </div>
        </div>
        <p className="card__meta">
          Разбор каждой карточки — по щелчку на ней ниже; сводка по всем занятиям и типичные
          ошибки — в разделе <Link to="/progress">«Мои результаты»</Link>.
          {session.repeat_failed && ' Проваленные карточки могли вернуться повторной выдачей — они помечены.'}
        </p>
      </div>
    );
  }

  if (showBriefing) {
    const nextIn = session.next_issue_in_seconds;
    return (
      <div className="briefing">
        <div className="briefing__head">
          <div>
            <div className="card__label">Инструктаж перед занятием</div>
            <h2 className="briefing__title">{session.title}</h2>
            <div className="card__meta">
              Преподаватель: {session.teacher_name} · ваша роль: {text.role}
            </div>
          </div>
        </div>
        <p>{text.task}</p>
        <div className="briefing__grid">
          <div>
            <b>Нормативы.</b> Взять в работу — за {session.pickup_deadline_seconds} с с момента
            поступления, обработать — за {session.handling_deadline_seconds} с. Они считаются
            автоматически, таймер виден на каждой карточке.
          </div>
          <div>
            <b>Поток.</b> Карточек запланировано: {session.cards_total}, новая поступает примерно
            каждые {session.call_interval_seconds} с — несколько будут в работе одновременно,
            расставляйте приоритеты сами.
            {nextIn !== null && nextIn > 0 && ` Первая — через ${Math.ceil(nextIn)} с.`}
            {session.cards_issued > 0 && ` Уже поступило: ${session.cards_issued}.`}
          </div>
          <div>
            <b>Зачёт.</b> Средний балл от {Math.round(session.pass_score * 100)} из 100 и не
            больше {session.max_critical_violations} критических нарушений.
            {session.repeat_failed && ' Проваленная карточка вернётся повторной выдачей в этом же занятии.'}
          </div>
        </div>
        <div className="actions">
          <button className="btn" onClick={start}>
            Приступить
          </button>
          <Link className="btn btn--ghost" to="/materials">
            Справочная база
          </Link>
        </div>
      </div>
    );
  }

  return (
    <p className="page-hint briefing__line">
      Занятие «{session.title}» · нормативы {session.pickup_deadline_seconds} / {session.handling_deadline_seconds} с ·
      обработано {session.cards_done} из {session.cards_total}
      {session.next_issue_in_seconds !== null && ` · следующая через ${Math.ceil(session.next_issue_in_seconds)} с`}
    </p>
  );
}
