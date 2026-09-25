import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api, operatorApi } from '../api/client';
import type {
  Call,
  CallerRole,
  CallerTurn,
  CallOutcome,
  Classification,
  FlagOption,
  FlagsResponse,
  OperatorEvaluation,
  PreviewResponse,
  SurveyOption,
} from '../api/types';
import { NotificationReasons } from '../components/NotificationReasons';
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

/**
 * Признак правила как пара «Да / Нет» с подписью слева — как в АРМ-112
 * («Угроза людям», «Проведена ли газификация»). Пока оператор не ответил,
 * не нажата ни одна кнопка: неотвеченный вопрос должен быть виден, а не
 * выглядеть как «нет».
 */
function YesNoFlag({
  option,
  value,
  disabled,
  onChange,
}: {
  option: FlagOption;
  value: boolean | null;
  disabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="arm-row">
      <div className="arm-row__label" title={option.hint ?? undefined}>
        {option.title}
      </div>
      <div className="arm-yn">
        <button
          type="button"
          disabled={disabled}
          className={`arm-yn__btn${value === true ? ' arm-yn__btn--on' : ''}`}
          onClick={() => onChange(true)}
        >
          Да
        </button>
        <button
          type="button"
          disabled={disabled}
          className={`arm-yn__btn${value === false ? ' arm-yn__btn--on' : ''}`}
          onClick={() => onChange(false)}
        >
          Нет
        </button>
      </div>
    </div>
  );
}

const EMPTY_FLAGS: FlagsResponse = { global: [], rule: [] };

/** Предпросмотр списка оповещения и ключ выбора, для которого он посчитан. */
interface PreviewState {
  key: string;
  data: PreviewResponse | null;
  failed: boolean;
}

/** Ответ бэкенда может прийти неполным (старая редакция, ошибка) — не падать. */
function normalizeFlags(raw: Partial<FlagsResponse> | null | undefined): FlagsResponse {
  const pick = (list: unknown): FlagOption[] =>
    Array.isArray(list)
      ? list
          .filter((f): f is FlagOption => !!f && typeof f === 'object' && typeof (f as FlagOption).key === 'string')
          .map((f) => ({ key: f.key, title: f.title || f.key, hint: f.hint ?? null }))
      : [];
  return { global: pick(raw?.global), rule: pick(raw?.rule) };
}

function normalizePreview(raw: Partial<PreviewResponse> | null | undefined): PreviewResponse {
  return {
    incident_type: typeof raw?.incident_type === 'string' ? raw.incident_type : null,
    // В предпросмотре нужны только оповещаемые службы; бэкенд и так отдаёт
    // только их, но старая редакция могла бы прислать и остальные.
    services: Array.isArray(raw?.services) ? raw.services.filter((s) => s && s.notified !== false) : [],
  };
}

/**
 * Заявитель на линии. Запись вызова — монолог, а работа оператора — диалог:
 * «какой подъезд?», «пострадавшие есть?». Отвечает модель по обстоятельствам
 * сценария и на неизвестное говорит «не знаю»; без модели заявитель молчит.
 * История сохраняется при попытке и после сдачи видна в разборе — что
 * спросил обучающийся и чего не спросил, тоже часть работы.
 */
function CallerDialogue({
  attemptId,
  initial,
  locked,
}: {
  attemptId: number;
  initial: CallerTurn[];
  locked: boolean;
}) {
  const [turns, setTurns] = useState<CallerTurn[]>(initial);
  const [question, setQuestion] = useState('');
  const [waiting, setWaiting] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<number | null>(null);

  const ask = useCallback(async () => {
    const text = question.trim();
    if (text.length < 2 || waiting) return;
    setWaiting(true);
    setNote(null);
    try {
      const result = await operatorApi.ask(attemptId, text);
      if (!result.available) {
        setNote('Заявитель не отвечает: языковая модель недоступна. Работайте по записи вызова.');
      } else {
        setTurns(result.dialogue);
        setRemaining(result.remaining);
        setQuestion('');
      }
    } catch (e) {
      setNote(e instanceof Error ? e.message : 'Не удалось задать вопрос');
    } finally {
      setWaiting(false);
    }
  }, [attemptId, question, waiting]);

  const exhausted = remaining === 0;
  return (
    <div className="dialogue">
      <div className="card__label">Уточнить у заявителя</div>
      {turns.length > 0 && (
        <ul className="dialogue__turns">
          {turns.map((turn, index) => (
            <li key={index}>
              <div className="dialogue__q">— {turn.question}</div>
              <div className="dialogue__a">— {turn.answer}</div>
            </li>
          ))}
        </ul>
      )}
      {!locked && !exhausted && (
        <div className="dialogue__ask">
          <input
            value={question}
            disabled={waiting}
            placeholder="Например: есть ли пострадавшие? какой подъезд?"
            maxLength={300}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') ask();
            }}
          />
          <button className="btn btn--ghost" onClick={ask} disabled={waiting || question.trim().length < 2}>
            {waiting ? 'Заявитель отвечает…' : 'Спросить'}
          </button>
        </div>
      )}
      {exhausted && !locked && (
        <div className="card__meta">Заявитель ответил на все вопросы, которые можно было задать, — заполняйте карточку.</div>
      )}
      {locked && turns.length === 0 && (
        <div className="card__meta">Уточняющих вопросов заявителю не задавалось.</div>
      )}
      {note && <div className="card__meta">{note}</div>}
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
  // Признаки опросной карты: что предлагает бэкенд и что отметил оператор.
  // «Нет» у признака правила — состояние только экрана: в карточку уходит
  // список отмеченных, а явный отказ нужен, чтобы отличить его от неответа.
  const [flagOptions, setFlagOptions] = useState<FlagsResponse>(EMPTY_FLAGS);
  const [flags, setFlags] = useState<string[]>([]);
  const [denied, setDenied] = useState<string[]>([]);
  // Предпросмотр хранится вместе с ключом выбора, для которого он посчитан:
  // показывается только совпадающий с текущим, поэтому устаревший ответ не
  // нужно вычищать отдельным сбросом состояния.
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [evaluation, setEvaluation] = useState<OperatorEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .call(attemptId)
      .then((loaded) => {
        setCall(loaded);
        // Поля восстанавливаются всегда: у сданной карточки — чтобы над
        // разбором была она, а не пустая форма; у незаконченной — из
        // черновика, который автосохранение пишет по ходу заполнения.
        // Обновление страницы или обрыв связи не должны стоить норматива.
        setGroup(loaded.chosen_group);
        setPath(loaded.chosen_path ?? []);
        setAddress(loaded.entered_address ?? '');
        setDescription(loaded.entered_description ?? '');
        setPhone(loaded.entered_caller_phone ?? '');
        setAddressParts(loaded.entered_address_parts ?? {});
        setFlags(Array.isArray(loaded.chosen_flags) ? loaded.chosen_flags : []);
        if (loaded.chosen_outcome) setOutcome(loaded.chosen_outcome);
        setReferral(loaded.chosen_referral_target ?? '');
      })
      .catch((e) => setError(String(e.message ?? e)));
    // Опросная карта — по редакции классификатора занятия, а не по
    // действующей: эталон вызова считается по ней же.
    operatorApi.surveyGroups(attemptId).then(setGroups).catch(() => undefined);
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
        const options = await operatorApi.surveyOptions(attemptId, group, path.slice(0, depth));
        if (options.length === 0) break;
        collected.push(options);
      }
      if (!cancelled) setLevels(collected);
    })().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [attemptId, group, path]);

  // Набор признаков зависит от того, к какому правилу привёл путь: при каждом
  // шаге запрашиваем заново, устаревший ответ отбрасываем. Признаки правила,
  // которых у нового правила нет, снимаются — они к нему не относятся.
  useEffect(() => {
    let cancelled = false;
    operatorApi
      .flags(attemptId, group, path)
      .then((raw) => {
        if (cancelled) return;
        const next = normalizeFlags(raw);
        setFlagOptions(next);
        const offered = new Set([...next.global, ...next.rule].map((f) => f.key));
        // Тот же массив, если снимать нечего: иначе каждый ответ дёргал бы
        // предпросмотр заново без изменения признаков.
        const prune = (current: string[]) => {
          const kept = current.filter((key) => offered.has(key));
          return kept.length === current.length ? current : kept;
        };
        setFlags(prune);
        setDenied(prune);
      })
      .catch(() => {
        // Без ручки признаков карточка остаётся рабочей: глобальные кнопки
        // сохраняем, какие были, признаки правила не показываем.
        if (!cancelled) setFlagOptions((current) => ({ global: current.global, rule: [] }));
      });
    return () => {
      cancelled = true;
    };
  }, [attemptId, group, path]);

  // Полоса служб — по текущему выбору оператора, как в настоящем АРМ-112:
  // пересчитывается при каждом изменении категории, пути или признаков.
  const previewKey =
    outcome === 'classify' && group ? [group, path.join('|'), flags.join('|')].join('\n') : null;
  useEffect(() => {
    if (!previewKey || !group) return;
    let cancelled = false;
    operatorApi
      .preview(attemptId, group, path, flags)
      .then((raw) => {
        if (!cancelled) setPreview({ key: previewKey, data: normalizePreview(raw), failed: false });
      })
      .catch(() => {
        if (!cancelled) setPreview({ key: previewKey, data: null, failed: true });
      });
    return () => {
      cancelled = true;
    };
  }, [attemptId, group, path, flags, previewKey]);

  const selectAt = useCallback((depth: number, label: string) => {
    // Выбор на верхнем уровне отменяет всё, что было выбрано ниже.
    setPath((current) => [...current.slice(0, depth), label]);
  }, []);

  const toggleFlag = useCallback((key: string) => {
    setFlags((current) =>
      current.includes(key) ? current.filter((k) => k !== key) : [...current, key],
    );
    setDenied((current) => current.filter((k) => k !== key));
  }, []);

  const answerFlag = useCallback((key: string, yes: boolean) => {
    setFlags((current) => {
      const without = current.filter((k) => k !== key);
      return yes ? [...without, key] : without;
    });
    setDenied((current) => {
      const without = current.filter((k) => k !== key);
      return yes ? without : [...without, key];
    });
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
          // Признаки имеют смысл только у зарегистрированного происшествия.
          flags: outcome === 'classify' ? flags : [],
        }),
      );
      setCall(await api.call(attemptId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить карточку');
    } finally {
      setBusy(false);
    }
  }, [attemptId, group, path, address, description, outcome, referral, phone, addressParts, flags]);

  // Подписи признаков для разбора: ключи классификатора фронт не расшифровывает,
  // но названия кнопок, которые прислал бэкенд, уже есть — используем их.
  const flagTitles = useMemo(() => {
    const titles: Record<string, string> = {};
    for (const f of [...flagOptions.global, ...flagOptions.rule]) titles[f.key] = f.title;
    return titles;
  }, [flagOptions]);

  // Автосохранение черновика: через полторы секунды после последнего
  // изменения, пока карточка не сдана. Сбой сохранения не мешает работе —
  // при сдаче всё уйдёт целиком; о нём говорит только строка состояния.
  const [draftState, setDraftState] = useState<'idle' | 'saving' | 'saved' | 'failed'>('idle');
  const [draftAt, setDraftAt] = useState<string | null>(null);
  const draftReady = useRef(false);
  useEffect(() => {
    if (!call || call.finished || evaluation !== null) return;
    // Первый прогон эффекта — это гидратация полей, а не правка оператора.
    if (!draftReady.current) {
      draftReady.current = true;
      return;
    }
    const timer = setTimeout(async () => {
      setDraftState('saving');
      try {
        await operatorApi.saveDraft(attemptId, {
          outcome,
          referral_target: referral,
          group: group ?? '',
          path,
          address,
          description,
          caller_phone: phone,
          address_parts: addressParts,
          flags,
        });
        setDraftState('saved');
        setDraftAt(new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
      } catch {
        setDraftState('failed');
      }
    }, 1500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outcome, referral, group, path, address, description, phone, addressParts, flags]);

  if (error && !call) return <div className="alert">{error}</div>;
  if (!call) return <div className="empty">Загрузка вызова…</div>;

  const locked = call.finished || evaluation !== null;
  const canSave = !busy && (outcome !== 'classify' || !!group);
  const shown = preview && preview.key === previewKey ? preview : null;

  return (
    <>
      <p className="page-hint">
        <Link to="/calls">← К списку вызовов</Link>
      </p>

      <div className="card">
        <div className="card__block legend">
          <CallAudio key={call.attempt_id} src={call.audio_url} />
          {call.is_repeat && (
            <div className="repeat-note">
              Повторная выдача. Это тот же вызов, с которым не удалось справиться
              в первый раз: он возвращён для повторной отработки. Выслушайте
              заявителя и заполните карточку заново — время считается с этого момента.
            </div>
          )}
          <div className="card__label" style={{ marginTop: 12 }}>
            Что сообщает заявитель
          </div>
          <div className="card__description">{call.legend}</div>
          <div className="legend__address">Со слов заявителя: {call.reported_address}</div>
          <CallerDialogue
            key={`dialogue-${call.attempt_id}`}
            attemptId={call.attempt_id}
            initial={call.dialogue ?? []}
            locked={locked}
          />
        </div>

        {/* Блок рабочей карточки «Регистрация и контроль». Появляется после
            сдачи: до неё регистрировать нечего, а контроль проводит
            преподаватель уже по готовой карточке. */}
        {call.finished && (
          <div className="card__block">
            <div className="card__label">Регистрация и контроль</div>
            <div className="card__meta">
              Карточка № {call.attempt_id} · зарегистрировал {call.registered_by}
              {call.registered_at &&
                `, ${new Date(call.registered_at).toLocaleString('ru-RU', DATE_FORMAT)}`}
            </div>
            <div className="card__meta">
              {call.control_at
                ? `Контроль провёл ${call.control_by ?? 'преподаватель'}, ${new Date(
                    call.control_at,
                  ).toLocaleString('ru-RU', DATE_FORMAT)}`
                : 'Контроль преподавателем ещё не проводился'}
            </div>
            {call.control_note && <div className="repeat-note">{call.control_note}</div>}
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <OutcomeChoice
          value={outcome}
          target={referral}
          disabled={locked}
          onChange={setOutcome}
          onTarget={setReferral}
        />
      </div>

      {/* Карточка по образцу АРМ-112: телефоны и таймер сверху, заявитель и
          адрес слева, классификатор с признаками справа, полоса служб снизу.
          Это отдельный контейнер, а не .card: у той overflow: hidden, и
          прилипающая полоса служб внутри неё не работала бы. */}
      <div className="arm">
        <div className="arm-head">
          <div className="arm-phone">
            <label className="arm-phone__label" htmlFor="phone-aon">
              АОН
            </label>
            {/* Номер определяется автоматически при поступлении вызова —
                оператор видит его сразу, как в рабочей системе, и не правит. */}
            <input
              id="phone-aon"
              className="arm-phone__value arm-ro"
              readOnly
              value={call.caller_phone_aon ?? 'не определился'}
            />
          </div>
          <div className="arm-phone">
            <label className="arm-phone__label" htmlFor="phone">
              предоставленный
            </label>
            <input
              id="phone"
              className="arm-phone__value"
              value={phone}
              disabled={locked}
              placeholder="со слов заявителя"
              onChange={(e) => setPhone(e.target.value)}
            />
          </div>
          <div className="arm-incident">
            <div>
              <div className="arm-incident__title">Происшествие № {call.attempt_id}</div>
              <div className="card__meta">
                Выдано {new Date(call.issued_at).toLocaleString('ru-RU', ISSUED_FORMAT)}
                {call.is_repeat && ' · повторная выдача'}
              </div>
            </div>
            <div className="arm-timer">
              <Timer
                issuedAt={call.issued_at}
                deadlineSeconds={call.deadline_seconds}
                frozenAt={call.finished ? call.elapsed_seconds : null}
              />
            </div>
          </div>
        </div>

        <div className="arm-col">
          <div className="arm-caller">
            <div className="field">
              <label htmlFor="caller-name">Фамилия и имя заявителя</label>
              <input id="caller-name" className="arm-ro" readOnly value={call.caller} />
            </div>
            <div className="field">
              <label htmlFor="caller-role">Статус</label>
              <input
                id="caller-role"
                className="arm-ro"
                readOnly
                value={call.caller_role ? ROLE_NAMES[call.caller_role] : 'не указан'}
              />
            </div>
          </div>

          <div className="arm-section-title">Адрес</div>
          <div className="address-grid">
            {ADDRESS_FIELDS.map((f) => (
              <div key={f.key} className={`field${f.wide ? ' field--wide' : ''}`}>
                <label htmlFor={`addr-${f.key}`}>
                  {f.label}
                  {f.hint && <span className="card__meta"> · {f.hint}</span>}
                </label>
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
            <label htmlFor="address">Описательный адрес</label>
            <input
              id="address"
              value={address}
              disabled={locked}
              placeholder="Адрес со слов заявителя, как сказано"
              onChange={(e) => setAddress(e.target.value)}
            />
          </div>

          <div className="arm-section-title">Описание со слов заявителя</div>
          <textarea
            className="comment-area"
            value={description}
            disabled={locked}
            placeholder="Детали, которые нельзя передать выбором признаков, но которые важны для реагирования"
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>

        <div className="arm-col">
          {outcome !== 'classify' ? (
            <div className="arm-note">
              {outcome === 'refer'
                ? 'Опросная карта не заполняется: вызов передаётся по принадлежности в систему-112 другого субъекта.'
                : 'Опросная карта не заполняется: обращение не является происшествием.'}
            </div>
          ) : (
            <>
              {flagOptions.global.length > 0 && (
                <div className="arm-flags">
                  {flagOptions.global.map((option) => {
                    const on = flags.includes(option.key);
                    return (
                      <button
                        key={option.key}
                        type="button"
                        disabled={locked}
                        aria-pressed={on}
                        title={option.hint ?? undefined}
                        className={`arm-flag${on ? ' arm-flag--on' : ''}`}
                        onClick={() => toggleFlag(option.key)}
                      >
                        {option.title}
                      </button>
                    );
                  })}
                </div>
              )}

              <div className="arm-section-title">добавить тип происшествия</div>

              <div className="arm-classifier">
                <div className="arm-row">
                  <label className="arm-row__label" htmlFor="group">
                    Категория
                  </label>
                  <div className="field" style={{ marginBottom: 0 }}>
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

                {flagOptions.rule.map((option) => (
                  <YesNoFlag
                    key={option.key}
                    option={option}
                    disabled={locked}
                    value={flags.includes(option.key) ? true : denied.includes(option.key) ? false : null}
                    onChange={(yes) => answerFlag(option.key, yes)}
                  />
                ))}
              </div>
            </>
          )}
        </div>

        {error && <div className="alert arm-alert">{error}</div>}

        <div className="arm-services">
          <div className="arm-services__title">Службы:</div>
          <div className="arm-services__list">
            {outcome !== 'classify' ? (
              <span className="arm-services__empty">
                {outcome === 'refer'
                  ? 'Список оповещения не формируется: вызов передаётся по принадлежности'
                  : 'Список оповещения не формируется: обращение не регистрируется'}
              </span>
            ) : shown?.failed ? (
              <span className="arm-services__empty">Предпросмотр списка оповещения недоступен</span>
            ) : !shown?.data?.incident_type ? (
              <span className="arm-services__empty">Определите тип происшествия</span>
            ) : shown.data.services.length === 0 ? (
              <span className="arm-services__empty">
                {shown.data.incident_type} — службы для оповещения не определены
              </span>
            ) : (
              shown.data.services.map((s) => (
                <span key={s.service} className="arm-service" title={s.reason}>
                  <span className="arm-service__name">{s.service}</span>{' '}
                  <span className="arm-service__type">{s.incident_type}</span>
                  <span className="arm-service__reason">{s.reason}</span>
                </span>
              ))
            )}
          </div>
          {!locked && (
            <>
              {draftState !== 'idle' && (
                <span className="card__meta arm-draft">
                  {draftState === 'saving' && 'черновик сохраняется…'}
                  {draftState === 'saved' && `черновик сохранён ${draftAt ?? ''}`}
                  {draftState === 'failed' && 'черновик не сохранился — при сдаче карточка уйдёт целиком'}
                </span>
              )}
              <button type="button" className="arm-save" onClick={submit} disabled={!canSave}>
                {busy ? 'Сохранение…' : 'Сохранить карточку'}
              </button>
            </>
          )}
        </div>
      </div>

      {evaluation && <OperatorReport evaluation={evaluation} flagTitles={flagTitles} />}
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
const ADDRESS_FIELDS: Array<{ key: string; label: string; wide?: boolean; hint?: string }> = [
  { key: 'subject', label: 'Субъект', wide: true },
  { key: 'settlement', label: 'Населённый пункт', wide: true },
  // Округ и район в рабочей карточке есть, но заявитель их не называет —
  // оператор берёт их из адресного справочника. Здесь они справочные:
  // заполняются по желанию и в оценке не участвуют.
  { key: 'district', label: 'Округ', hint: 'справочно' },
  { key: 'area', label: 'Район', hint: 'справочно' },
  { key: 'street', label: 'Улица', wide: true },
  { key: 'house', label: 'Дом' },
  { key: 'building', label: 'Корпус' },
  { key: 'structure', label: 'Строение' },
  { key: 'flat', label: 'Квартира' },
  { key: 'entrance', label: 'Подъезд' },
  { key: 'floor', label: 'Этаж' },
  { key: 'intercom', label: 'Код домофона' },
  // Для места без номера дома объект и ориентиры — это и есть адрес.
  { key: 'object', label: 'Объект', wide: true, hint: 'магазин, станция метро, парк' },
  { key: 'access', label: 'Ориентиры, как проехать', wide: true, hint: '«напротив ТЦ», «во дворе у 5 подъезда»' },
];

const DATE_FORMAT: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
};

/** В шапке АРМ-112 время выдачи стоит с секундами: по нему сверяют таймер. */
const ISSUED_FORMAT: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
};

const OUTCOME_NAMES: Record<CallOutcome, string> = {
  classify: 'зарегистрировать происшествие',
  refer: 'передать по принадлежности',
  reject: 'не регистрировать: не происшествие',
};

/**
 * Разбор признаков опросной карты. Пропущенный признак — красным: из-за него
 * служба не получила оповещение; лишний — жёлтым: он добавил службу без
 * оснований; верно отмеченный — зелёным. Списки могут отсутствовать у ответа
 * старой редакции бэкенда — тогда блока просто нет.
 */
function FlagsReview({
  classification,
  titles,
}: {
  classification: Classification;
  titles: Record<string, string>;
}) {
  const expected = classification.expected_flags ?? [];
  const chosen = classification.chosen_flags ?? [];
  const missed = new Set(classification.missed_flags ?? []);
  const extra = classification.extra_flags ?? [];
  const name = (key: string) => titles[key] ?? key;

  // У сценария признаки не размечены — сверки не было. Сказать об этом
  // прямо честнее, чем рисовать зелёные галочки за отсутствие проверки.
  if (classification.flags_checked === false) {
    return (
      <div style={{ marginTop: 10 }}>
        <b>Признаки опросной карты:</b>{' '}
        <span className="card__meta">
          в этом вызове не размечены, выбор оператора не оценивался
          {chosen.length > 0 && ` (отмечено: ${chosen.map(name).join(', ')})`}
        </span>
      </div>
    );
  }
  if (expected.length === 0 && chosen.length === 0 && extra.length === 0) return null;
  const correct = chosen.filter((key) => expected.includes(key));

  return (
    <div style={{ marginTop: 10 }}>
      <b>Признаки опросной карты:</b>
      <div className="arm-flagchips">
        {correct.map((key) => (
          <span key={`ok-${key}`} className="chip chip--ok" title="отмечен верно">
            {name(key)}
          </span>
        ))}
        {[...missed].map((key) => (
          <span key={`missed-${key}`} className="chip chip--danger" title="есть в вызове, но не отмечен">
            не отмечен: {name(key)}
          </span>
        ))}
        {extra.map((key) => (
          <span key={`extra-${key}`} className="chip chip--warn" title="отмечен, но в вызове его нет">
            лишний: {name(key)}
          </span>
        ))}
        {expected.length === 0 && chosen.length === 0 && (
          <span className="card__meta">признаков в вызове нет, и отмечено ничего не было</span>
        )}
      </div>
    </div>
  );
}

function OperatorReport({
  evaluation,
  flagTitles,
}: {
  evaluation: OperatorEvaluation;
  flagTitles: Record<string, string>;
}) {
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
            <FlagsReview classification={classification} titles={flagTitles} />
            {classification.missed_services.length > 0 && (
              <div className="missed">
                <b>Не получили бы оповещение:</b>{' '}
                {classification.missed_services.join(', ')}
              </div>
            )}
            <NotificationReasons reasons={classification.notification_reasons} />
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
            {violation.quote && (
              <div className="violation__quote">Со слов заявителя: «{violation.quote}»</div>
            )}
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
