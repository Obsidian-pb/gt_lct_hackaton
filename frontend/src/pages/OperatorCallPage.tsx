import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Call, CallerRole, CallOutcome, OperatorEvaluation, SurveyOption } from '../api/types';
import { Timer } from '../components/Timer';

/**
 * Голосовая имитация звонка заявителя.
 *
 * Речь записана заранее и лежит в раздаче фронтенда: браузер только
 * проигрывает готовый файл. Синтезировать её на стороне клиента не вышло —
 * в Firefox движок после отмены речи замолкал до перезагрузки страницы,
 * и вылечить это со стороны приложения оказалось невозможно.
 *
 * Запись может отсутствовать: у сценариев, придуманных нейросетью, её нет.
 * Интерфейс обязан работать и без звука — текст вызова виден всегда.
 */
function CallAudio({ src }: { src: string | null }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [answered, setAnswered] = useState(false);
  const [broken, setBroken] = useState(false);

  const play = useCallback(() => {
    const element = audio.current;
    if (!element) return;
    setAnswered(true);
    // Слушать вызов заново заявитель начинает с начала, а не с места обрыва.
    element.currentTime = 0;
    element.play().then(
      () => setPlaying(true),
      () => setBroken(true),
    );
  }, []);

  const interrupt = useCallback(() => {
    audio.current?.pause();
    setPlaying(false);
  }, []);

  if (!src || broken) {
    return (
      <div className="call-audio call-audio--mute">
        Запись вызова недоступна. Текст обращения заявителя — ниже.
      </div>
    );
  }

  return (
    <div className="call-audio">
      <audio
        ref={audio}
        src={src}
        preload="auto"
        onEnded={() => setPlaying(false)}
        onError={() => setBroken(true)}
      />
      <span className={`call-audio__dot${playing ? ' call-audio__dot--live' : ''}`} />
      <span className="call-audio__label">
        {playing ? 'Заявитель говорит…' : answered ? 'Вызов прослушан' : 'Входящий вызов'}
      </span>
      <div className="app-header__spacer" />
      {playing ? (
        <button className="btn btn--ghost" onClick={interrupt}>
          Прервать
        </button>
      ) : (
        <button className="btn" onClick={play}>
          {answered ? 'Прослушать снова' : 'Ответить на вызов'}
        </button>
      )}
    </div>
  );
}

/**
 * Первое решение оператора: наше ли это происшествие и происшествие ли вообще.
 *
 * Стоит до опросной карты намеренно. Классифицировать вызов из другого
 * субъекта бессмысленно — в московском классификаторе такого происшествия
 * нет, — а опросная карта, открытая сразу, подталкивает заполнять её не глядя
 * на адрес. Экзаменационные билеты проверяют ровно эту привычку.
 */
const OUTCOMES: Array<{ value: CallOutcome; title: string; hint: string }> = [
  {
    value: 'classify',
    title: 'Происшествие в Москве',
    hint: 'Заполнить опросную карту и зарегистрировать карточку',
  },
  {
    value: 'refer',
    title: 'Другой субъект',
    hint: 'Передать по принадлежности в систему-112 своего региона',
  },
  {
    value: 'reject',
    title: 'Не происшествие',
    hint: 'Обращение не относится к ведению Системы-112',
  },
];

function OutcomeChoice({
  value,
  target,
  disabled,
  onChange,
  onTarget,
}: {
  value: CallOutcome;
  target: string;
  disabled: boolean;
  onChange: (value: CallOutcome) => void;
  onTarget: (value: string) => void;
}) {
  return (
    <div className="card__block">
      <div className="card__label">Решение по вызову</div>
      <div className="outcomes">
        {OUTCOMES.map((option) => (
          <button
            key={option.value}
            type="button"
            disabled={disabled}
            className={`outcome${value === option.value ? ' outcome--active' : ''}`}
            onClick={() => onChange(option.value)}
          >
            <span className="outcome__title">{option.title}</span>
            <span className="outcome__hint">{option.hint}</span>
          </button>
        ))}
      </div>

      {value === 'refer' && (
        <div className="field" style={{ maxWidth: 460, marginTop: 12 }}>
          <label htmlFor="referral">Субъект Российской Федерации</label>
          <input
            id="referral"
            value={target}
            disabled={disabled}
            placeholder="Например: Московская область"
            onChange={(e) => onTarget(e.target.value)}
          />
        </div>
      )}
    </div>
  );
}

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
  const [outcome, setOutcome] = useState<CallOutcome>('classify');
  const [phone, setPhone] = useState('');
  const [addressParts, setAddressParts] = useState<Record<string, string>>({});
  const [referral, setReferral] = useState('');
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
    // Группа обязательна только там, где вызов положено классифицировать.
    if (outcome === 'classify' && !group) return;
    setBusy(true);
    setError(null);
    try {
      setEvaluation(
        await api.classifyCall(attemptId, {
          outcome,
          referral_target: referral,
          group: group ?? '',
          path,
          address,
          description,
          caller_phone: phone,
          address_parts: addressParts,
        }),
      );
      setCall(await api.call(attemptId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить карточку');
    } finally {
      setBusy(false);
    }
  }, [attemptId, group, path, address, description, outcome, referral, phone, addressParts]);

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
            <div className="card__meta">
              Заявитель: {call.caller}
              {call.caller_role && ` · ${ROLE_NAMES[call.caller_role]}`}
            </div>
            {/* Номер определяется автоматически при поступлении вызова —
                оператор видит его сразу, как в рабочей системе. */}
            <div className="card__meta">
              Определившийся номер: {call.caller_phone_aon ?? 'не определился'}
            </div>
          </div>
          <Timer
            issuedAt={call.issued_at}
            deadlineSeconds={call.deadline_seconds}
            frozenAt={call.finished ? call.elapsed_seconds : null}
          />
        </div>

        <div className="card__block legend">
          <CallAudio key={call.attempt_id} src={call.audio_url} />
          <div className="card__label" style={{ marginTop: 12 }}>
            Что сообщает заявитель
          </div>
          <div className="card__description">{call.legend}</div>
          <div className="legend__address">Со слов заявителя: {call.reported_address}</div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <OutcomeChoice
          value={outcome}
          target={referral}
          disabled={locked}
          onChange={setOutcome}
          onTarget={setReferral}
        />

        {outcome === 'classify' && (
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
        )}

        <div className="card__block">
          <div className="field" style={{ maxWidth: 460 }}>
            <label htmlFor="phone">Телефон для связи с заявителем</label>
            <input
              id="phone"
              value={phone}
              disabled={locked}
              placeholder="Запишите номер со слов заявителя"
              onChange={(e) => setPhone(e.target.value)}
            />
          </div>
          <div className="card__label" style={{ marginTop: 6 }}>
            Адрес происшествия по частям
          </div>
          <div className="address-grid">
            {ADDRESS_FIELDS.map((f) => (
              <div key={f.key} className={`field${f.wide ? ' field--wide' : ''}`}>
                <label htmlFor={`addr-${f.key}`}>{f.label}</label>
                <input
                  id={`addr-${f.key}`}
                  value={addressParts[f.key] ?? ''}
                  disabled={locked}
                  onChange={(e) =>
                    setAddressParts((current) => ({ ...current, [f.key]: e.target.value }))
                  }
                />
              </div>
            ))}
          </div>

          <div className="field">
            <label htmlFor="address">Адрес со слов заявителя, как сказано</label>
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
              <button
                className="btn"
                onClick={submit}
                disabled={busy || (outcome === 'classify' && !group)}
              >
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

const ROLE_NAMES: Record<CallerRole, string> = {
  participant: 'участник происшествия',
  witness: 'очевидец',
  relative: 'родственник',
};

/**
 * Адрес в карточке Системы-112 хранится по частям, а не строкой: от их
 * полноты зависит, найдут ли место силы реагирования. Порядок — от общего
 * к частному, как его и выясняют в разговоре.
 */
const ADDRESS_FIELDS: Array<{ key: string; label: string; wide?: boolean }> = [
  { key: 'subject', label: 'Субъект', wide: true },
  { key: 'settlement', label: 'Населённый пункт', wide: true },
  { key: 'street', label: 'Улица', wide: true },
  { key: 'house', label: 'Дом' },
  { key: 'building', label: 'Корпус' },
  { key: 'structure', label: 'Строение' },
  { key: 'flat', label: 'Квартира' },
  { key: 'entrance', label: 'Подъезд' },
  { key: 'floor', label: 'Этаж' },
  { key: 'intercom', label: 'Код домофона' },
];

const OUTCOME_NAMES: Record<CallOutcome, string> = {
  classify: 'зарегистрировать происшествие',
  refer: 'передать по принадлежности',
  reject: 'не регистрировать: не происшествие',
};

function OperatorReport({ evaluation }: { evaluation: OperatorEvaluation }) {
  const classification = evaluation.classification;
  const outcomeWrong =
    evaluation.chosen_outcome !== null &&
    evaluation.chosen_outcome !== evaluation.expected_outcome;
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card__block">
        <div className="card__label">Разбор обработки вызова</div>
        <div className="score">
          <span className="score__value">{Math.round(evaluation.score * 100)}</span>
          <span className="card__meta">из 100</span>
        </div>

        {outcomeWrong && (
          <div className="classify-result">
            <div>
              <b>Решение по вызову:</b>{' '}
              <span className="chip chip--danger">
                {OUTCOME_NAMES[evaluation.chosen_outcome!]}
              </span>
            </div>
            <div style={{ marginTop: 6 }}>
              <b>Следовало:</b>{' '}
              <span className="chip chip--ok">
                {OUTCOME_NAMES[evaluation.expected_outcome]}
              </span>
              {evaluation.expected_referral_target && (
                <span className="card__meta" style={{ marginLeft: 8 }}>
                  в «{evaluation.expected_referral_target}»
                </span>
              )}
            </div>
          </div>
        )}

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
