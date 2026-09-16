import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Call, OperatorEvaluation, SurveyOption } from '../api/types';
import { Timer } from '../components/Timer';

/** Шаг опросной карты: выбранный признак и варианты следующего уровня. */
function SurveyStep({
  title,
  options,
  selected,
  onSelect,
  disabled,
}: {
  title: string;
  options: SurveyOption[];
  selected: string | null;
  onSelect: (label: string) => void;
  disabled: boolean;
}) {
  if (options.length === 0) return null;
  return (
    <div className="survey__step">
      <div className="card__label">{title}</div>
      <div className="survey__options">
        {options.map((option) => (
          <button
            key={option.label}
            type="button"
            disabled={disabled}
            className={`survey__option${selected === option.label ? ' survey__option--active' : ''}`}
            onClick={() => onSelect(option.label)}
            title={option.incident_type ?? undefined}
          >
            {option.label}
            {option.is_final && <span className="survey__final">тип определён</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

export function OperatorCallPage() {
  const { id } = useParams();
  const attemptId = Number(id);

  const [call, setCall] = useState<Call | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [group, setGroup] = useState<string | null>(null);
  const [path, setPath] = useState<string[]>([]);
  const [levels, setLevels] = useState<SurveyOption[][]>([]);
  const [address, setAddress] = useState('');
  const [description, setDescription] = useState('');
  const [evaluation, setEvaluation] = useState<OperatorEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.call(attemptId).then(setCall).catch((e) => setError(String(e.message ?? e)));
    api.surveyGroups().then(setGroups).catch(() => undefined);
  }, [attemptId]);

  // Каждый выбор открывает следующий уровень опросной карты.
  useEffect(() => {
    if (!group) {
      setLevels([]);
      return;
    }
    let cancelled = false;
    (async () => {
      const collected: SurveyOption[][] = [];
      for (let depth = 0; depth <= path.length; depth += 1) {
        const options = await api.surveyOptions(group, path.slice(0, depth));
        if (options.length === 0) break;
        collected.push(options);
      }
      if (!cancelled) setLevels(collected);
    })().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [group, path]);

  const selectAt = useCallback((depth: number, label: string) => {
    // Выбор на верхнем уровне отменяет всё, что было выбрано ниже.
    setPath((current) => [...current.slice(0, depth), label]);
  }, []);

  const submit = useCallback(async () => {
    if (!group) return;
    setBusy(true);
    setError(null);
    try {
      setEvaluation(
        await api.classifyCall(attemptId, { group, path, address, description }),
      );
      setCall(await api.call(attemptId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить карточку');
    } finally {
      setBusy(false);
    }
  }, [attemptId, group, path, address, description]);

  if (error && !call) return <div className="alert">{error}</div>;
  if (!call) return <div className="empty">Загрузка вызова…</div>;

  const locked = call.finished || evaluation !== null;

  return (
    <>
      <p className="page-hint">
        <Link to="/calls">← К списку вызовов</Link>
      </p>

      <div className="card">
        <div className="card__head">
          <div style={{ flex: 1 }}>
            <h1 className="card__type">Входящий вызов</h1>
            <div className="card__meta">Заявитель: {call.caller}</div>
          </div>
          <Timer
            issuedAt={call.issued_at}
            deadlineSeconds={call.deadline_seconds}
            frozenAt={call.finished ? call.elapsed_seconds : null}
          />
        </div>

        <div className="card__block legend">
          <div className="card__label">Что сообщает заявитель</div>
          <div className="card__description">{call.legend}</div>
          <div className="legend__address">Со слов заявителя: {call.reported_address}</div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card__block">
          <div className="card__label">Опросная карта — классифицируйте происшествие</div>

          <div className="field" style={{ maxWidth: 460, marginTop: 8 }}>
            <label htmlFor="group">Категория происшествия</label>
            <select
              id="group"
              value={group ?? ''}
              disabled={locked}
              onChange={(e) => {
                setGroup(e.target.value || null);
                setPath([]);
              }}
            >
              <option value="">— выберите —</option>
              {groups.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </div>

          {levels.map((options, depth) => (
            <SurveyStep
              key={depth}
              title={`Признак ${depth + 1}`}
              options={options}
              selected={path[depth] ?? null}
              disabled={locked}
              onSelect={(label) => selectAt(depth, label)}
            />
          ))}
        </div>

        <div className="card__block">
          <div className="field">
            <label htmlFor="address">Адрес происшествия</label>
            <input
              id="address"
              value={address}
              disabled={locked}
              placeholder="Уточните адрес у заявителя и внесите его в карточку"
              onChange={(e) => setAddress(e.target.value)}
            />
          </div>
          <div className="card__label" style={{ marginTop: 10 }}>
            Описание происшествия
          </div>
          <textarea
            className="comment-area"
            value={description}
            disabled={locked}
            placeholder="Детали, которые нельзя передать выбором признаков, но которые важны для реагирования"
            onChange={(e) => setDescription(e.target.value)}
          />

          {error && <div className="alert" style={{ marginTop: 10 }}>{error}</div>}

          {!locked && (
            <div className="actions">
              <button className="btn" onClick={submit} disabled={busy || !group}>
                {busy ? 'Сохранение…' : 'Сохранить карточку'}
              </button>
            </div>
          )}
        </div>
      </div>

      {evaluation && <OperatorReport evaluation={evaluation} />}
    </>
  );
}

function OperatorReport({ evaluation }: { evaluation: OperatorEvaluation }) {
  const classification = evaluation.classification;
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card__block">
        <div className="card__label">Разбор обработки вызова</div>
        <div className="score">
          <span className="score__value">{Math.round(evaluation.score * 100)}</span>
          <span className="card__meta">из 100</span>
        </div>

        {classification && (
          <div className="classify-result">
            <div>
              <b>Зарегистрирован тип:</b>{' '}
              <span className={classification.correct ? 'chip chip--ok' : 'chip chip--danger'}>
                {classification.chosen_incident_type ?? 'не определён'}
              </span>
            </div>
            {!classification.correct && (
              <div style={{ marginTop: 6 }}>
                <b>Следовало:</b>{' '}
                <span className="chip chip--ok">{classification.expected_incident_type}</span>
                <span className="card__meta" style={{ marginLeft: 8 }}>
                  совпало признаков: {classification.matched_depth} из{' '}
                  {classification.expected_depth}
                </span>
              </div>
            )}
            {classification.missed_services.length > 0 && (
              <div className="missed">
                <b>Не получили бы оповещение:</b>{' '}
                {classification.missed_services.join(', ')}
              </div>
            )}
          </div>
        )}

        {evaluation.violations.map((violation, index) => (
          <div className={`violation violation--${violation.severity}`} key={index}>
            <div className="violation__head">
              <span className="violation__code">{violation.code}</span>
              <span className="violation__title">{violation.title}</span>
              <span className="chip chip--neutral">{violation.severity}</span>
            </div>
            <div>{violation.detail}</div>
            {violation.example && (
              <div className="violation__example">
                <b>Почему это важно:</b> {violation.example}
              </div>
            )}
          </div>
        ))}

        {evaluation.violations.length === 0 && <p>Вызов обработан без замечаний.</p>}

        {evaluation.grammar_issues.length > 0 && (
          <>
            <div className="card__label" style={{ marginTop: 14 }}>
              Замечания к грамматике описания
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
