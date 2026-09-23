import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Card, Evaluation } from '../api/types';
import { useAuth } from '../auth';
import { EvaluationReport } from '../components/EvaluationReport';
import { Timer } from '../components/Timer';

export function CardPage() {
  const { id } = useParams();
  const attemptId = Number(id);
  const { user } = useAuth();

  const [card, setCard] = useState<Card | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [comment, setComment] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Открытие карточки проставляет технический статус «Получена службой».
    api
      .openCard(attemptId)
      .then(setCard)
      .catch((e) => setError(e instanceof Error ? e.message : 'Карточка недоступна'));
  }, [attemptId]);

  useEffect(() => {
    if (card?.finished && !evaluation) {
      api.evaluation(attemptId).then(setEvaluation).catch(() => undefined);
    }
  }, [card?.finished, evaluation, attemptId]);

  // Смысловая проверка идёт фоном — дожидаемся её, опрашивая результат.
  const pollTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!evaluation?.llm_pending) return;
    pollTimer.current = window.setInterval(async () => {
      try {
        const fresh = await api.evaluation(attemptId);
        setEvaluation(fresh);
      } catch {
        // Оценка ещё не готова — повторим на следующем шаге.
      }
    }, 1500);
    return () => {
      if (pollTimer.current) window.clearInterval(pollTimer.current);
    };
  }, [evaluation?.llm_pending, attemptId]);

  const commentRequired = selected != null && card?.comment_required_for.includes(selected);

  const submitStatus = useCallback(async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      setCard(await api.setStatus(attemptId, selected, comment.trim() || null));
      setSelected(null);
      setComment('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось проставить статус');
    } finally {
      setBusy(false);
    }
  }, [attemptId, selected, comment]);

  const finishWork = useCallback(async () => {
    setBusy(true);
    try {
      setEvaluation(await api.finish(attemptId));
      setCard(await api.card(attemptId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось завершить работу');
    } finally {
      setBusy(false);
    }
  }, [attemptId]);

  if (error && !card) return <div className="alert">{error}</div>;
  if (!card) return <div className="empty">Загрузка карточки…</div>;

  return (
    <>
      <p className="page-hint">
        <Link to="/">← К списку происшествий</Link>
      </p>

      <div className="card">
        <div className="card__head">
          <div style={{ flex: 1 }}>
            <h1 className="card__type">{card.incident_type}</h1>
            <div className="card__meta">
              Карточка № {card.attempt_id} · направлена{' '}
              {new Date(card.issued_at).toLocaleTimeString('ru-RU')} ·{' '}
              статус карточки: {card.card_status}
              {card.is_repeat && ' · повторная выдача'}
            </div>
            {card.is_repeat && (
              <div className="repeat-note">
                Повторная выдача. Это тот же вызов, с которым не удалось справиться
                в первый раз: карточка возвращена для повторной отработки. Норматив
                считается заново, с момента этого направления.
              </div>
            )}
          </div>
          <Timer
            issuedAt={card.issued_at}
            deadlineSeconds={card.deadline_seconds}
            frozenAt={card.finished ? card.elapsed_seconds : null}
          />
        </div>

        <div className="card__block">
          <div className="card__label">Адрес происшествия</div>
          <div className="card__address">{card.address}</div>
        </div>

        <div className="card__block">
          <div className="card__label">Описание</div>
          <div className="card__description">{card.description}</div>
        </div>

        {card.caller && (
          <div className="card__block">
            <div className="card__label">Заявитель</div>
            <div>{card.caller}</div>
          </div>
        )}

        {Object.keys(card.notified_services).length > 0 && (
          <div className="card__block notify">
            <div className="card__label">
              Список оповещения — сформирован автоматически по ЕКП
            </div>
            <div className="notify__grid">
              {Object.entries(card.notified_services).map(([service, type]) => (
                <div
                  key={service}
                  className={`notify__item${service === user?.service_ekp_name ? ' notify__own' : ''}`}
                >
                  <div className="notify__service">{service}</div>
                  <div className="notify__type">{type}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="card__block">
          <div className="card__label">Статус реагирования вашей службы</div>

          {error && <div className="alert">{error}</div>}

          {card.finished ? (
            <p className="card__meta">
              Работа с карточкой завершена. Текущий статус: {card.current_status ?? 'не проставлен'}.
            </p>
          ) : (
            <>
              <div className="statuses">
                {card.available_statuses.map((status) => (
                  <button
                    key={status}
                    type="button"
                    className={`status-btn${selected === status ? ' status-btn--active' : ''}`}
                    onClick={() => setSelected(status)}
                  >
                    {status}
                  </button>
                ))}
              </div>

              {selected && (
                <>
                  <textarea
                    className="comment-area"
                    placeholder="Комментарий: причина отказа, сведения о передаче информации в другие службы, уточнённые данные"
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                  />
                  {commentRequired && !comment.trim() && (
                    <div className="comment-note">
                      Для статуса «{selected}» комментарий обязателен. Система примет статус
                      и без него, но это будет зафиксировано как нарушение.
                    </div>
                  )}
                  <div className="actions">
                    <button className="btn" onClick={submitStatus} disabled={busy}>
                      Проставить статус
                    </button>
                    <button
                      className="btn btn--ghost"
                      onClick={() => setSelected(null)}
                      disabled={busy}
                    >
                      Отмена
                    </button>
                  </div>
                </>
              )}

              {!selected && !evaluation && (
                <div className="actions">
                  <button className="btn btn--ghost" onClick={finishWork} disabled={busy}>
                    Завершить работу с карточкой
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {evaluation && (
        <div style={{ marginTop: 18 }}>
          <EvaluationReport evaluation={evaluation} />
        </div>
      )}
    </>
  );
}
