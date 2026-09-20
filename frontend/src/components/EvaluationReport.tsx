import type { Evaluation } from '../api/types';

function scoreLabel(score: number): string {
  if (score >= 0.9) return 'без замечаний';
  if (score >= 0.7) return 'с замечаниями';
  if (score >= 0.4) return 'существенные ошибки';
  return 'грубые нарушения';
}

export function EvaluationReport({ evaluation }: { evaluation: Evaluation }) {
  const percent = Math.round(evaluation.score * 100);

  return (
    <div className="card">
      <div className="card__block">
        <div className="card__label">Разбор действий</div>
        <div className="score">
          <span className="score__value">{percent}</span>
          <span className="card__meta">из 100 — {scoreLabel(evaluation.score)}</span>
        </div>

        <div className="criteria">
          {Object.entries(evaluation.criteria).map(([name, passed]) => (
            <div className="criteria__row" key={name}>
              <span className={passed ? 'chip chip--ok' : 'chip chip--danger'}>
                {passed ? 'соблюдено' : 'нарушено'}
              </span>
              <span>{name}</span>
            </div>
          ))}
        </div>

        {/* Примечание преподавателя — выше автоматических замечаний: это
            адресный разбор живого человека, а не вывод проверок. */}
        {evaluation.teacher_feedback && (
          <div className="draft__note">
            <b>Примечание преподавателя</b>
            {evaluation.teacher_feedback_by ? ` (${evaluation.teacher_feedback_by})` : ''}:{' '}
            {evaluation.teacher_feedback}
          </div>
        )}

        {evaluation.llm_pending && (
          <div className="pending">
            <span className="spinner" />
            Идёт смысловая проверка комментариев. Оценка соблюдения норматива и статусов
            уже учтена.
          </div>
        )}

        {!evaluation.llm_pending && !evaluation.llm_available && evaluation.llm_summary && (
          <div className="alert">{evaluation.llm_summary}</div>
        )}

        {evaluation.violations.length === 0 && !evaluation.llm_pending ? (
          <p>
            {evaluation.llm_available
              ? 'Нарушений не выявлено. Карточка обработана в соответствии с регламентом.'
              : 'По выполненным проверкам нарушений не выявлено. Оценка неполная.'}
          </p>
        ) : (
          evaluation.violations.map((violation, index) => (
            <div className={`violation violation--${violation.severity}`} key={index}>
              <div className="violation__head">
                <span className="violation__code">{violation.code}</span>
                <span className="violation__title">{violation.title}</span>
                <span className="chip chip--neutral">{violation.severity}</span>
              </div>
              <div>{violation.detail}</div>
              {violation.example && (
                <div className="violation__example">
                  <b>Пример из памятки:</b> {violation.example}
                </div>
              )}
            </div>
          ))
        )}

        {evaluation.grammar_issues.length > 0 && (
          <>
            <div className="card__label" style={{ marginTop: 16 }}>
              Замечания к грамматике
            </div>
            <ul>
              {evaluation.grammar_issues.map((issue, index) => (
                <li key={index}>{issue}</li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
