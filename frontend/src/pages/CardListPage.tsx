import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { Card } from '../api/types';
import { Timer, cardDeadline } from '../components/Timer';

/** Красная индикация у статусов, которые попадают в отдел контроля. */
const PROBLEM_STATUSES = new Set(['Не оповещено', 'Отказ', 'Не завершено']);

function statusChipClass(status: string): string {
  if (PROBLEM_STATUSES.has(status)) return 'chip chip--danger';
  if (status === 'Завершена') return 'chip chip--ok';
  return 'chip chip--neutral';
}

export function CardListPage() {
  const navigate = useNavigate();
  const [cards, setCards] = useState<Card[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .myCards()
      .then(setCards)
      .catch((e) => setError(e instanceof Error ? e.message : 'Не удалось загрузить карточки'));
  }, []);

  if (error) return <div className="alert">{error}</div>;
  if (!cards) return <div className="empty">Загрузка…</div>;
  if (cards.length === 0) {
    return <div className="empty">В вашу службу пока не направлено ни одной карточки.</div>;
  }

  const pending = cards.filter((c) => !c.finished).length;
  const hasRepeats = cards.some((c) => c.is_repeat);

  return (
    <>
      <h1 className="page-title">Происшествия</h1>
      <p className="page-hint">
        Карточки, направленные в вашу службу. Подтвердите приём информации в течение норматива —
        иначе карточка перейдёт в статус «Не оповещено». В работе: {pending} из {cards.length}.
      </p>
      {hasRepeats && (
        <p className="page-hint">
          Карточка с пометкой «Повторная выдача» — тот же вызов, с которым не удалось
          справиться в первый раз. Он возвращён для повторной отработки: пройдите его заново.
        </p>
      )}

      <table className="card-table">
        <thead>
          <tr>
            <th style={{ width: '50%' }}>Происшествие</th>
            <th>Норматив</th>
            <th>Статус реагирования</th>
            <th>Статус карточки</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((card) => (
            <tr key={card.attempt_id} onClick={() => navigate(`/cards/${card.attempt_id}`)}>
              <td>
                <div className="card-table__type">
                  {card.incident_type}
                  {card.is_repeat && (
                    <>
                      {' '}
                      <span className="chip chip--warn">Повторная выдача</span>
                    </>
                  )}
                </div>
                <div className="card-table__address">{card.address}</div>
              </td>
              <td>
                <Timer
                  issuedAt={card.issued_at}
                  deadlineSeconds={cardDeadline(card)}
                  frozenAt={card.finished ? card.elapsed_seconds : null}
                />
              </td>
              <td>
                {card.current_status ? (
                  <span className="chip chip--neutral">{card.current_status}</span>
                ) : (
                  <span className="chip chip--warn">не проставлен</span>
                )}
              </td>
              <td>
                <span className={statusChipClass(card.card_status)}>{card.card_status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
