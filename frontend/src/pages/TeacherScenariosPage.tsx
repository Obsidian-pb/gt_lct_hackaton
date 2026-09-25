import { useCallback, useEffect, useState } from 'react';

import { api, teacherApi } from '../api/client';
import type { Catalog, GrammarCheck, Scenario } from '../api/types';

/**
 * Признаки опросной карты вызова: то, что заявитель назвал и что оператор
 * обязан отметить. Из речи распознаются только явные упоминания, поэтому
 * преподаватель может поправить их здесь — иначе верно услышанные
 * пострадавшие засчитались бы обучающемуся как лишний признак.
 */
const GLOBAL_FLAGS: Array<{ key: string; title: string }> = [
  { key: 'пострадавшие', title: 'Пострадавшие' },
  { key: 'пострадавшие_не_на_месте', title: 'Нет на месте / Отказ от скорой' },
  { key: 'нет_доступа', title: 'Нет доступа / Заблокированные' },
];

function ScenarioFlags({ scenario }: { scenario: Scenario }) {
  const [flags, setFlags] = useState<string[]>(scenario.flags ?? []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle(key: string) {
    const next = flags.includes(key) ? flags.filter((f) => f !== key) : [...flags, key];
    setSaving(true);
    setError(null);
    try {
      const saved = await api.editScenario(scenario.id, { flags: next });
      setFlags(saved.flags ?? next);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить признаки');
    } finally {
      setSaving(false);
    }
  }

  const other = flags.filter((f) => !GLOBAL_FLAGS.some((g) => g.key === f));
  return (
    <div className="draft__flags">
      <span className="card__meta">Признаки вызова:</span>
      {GLOBAL_FLAGS.map((flag) => (
        <button
          key={flag.key}
          type="button"
          disabled={saving}
          className={`chip ${flags.includes(flag.key) ? 'chip--ok' : 'chip--neutral'}`}
          title={flags.includes(flag.key) ? 'Отмечен — нажмите, чтобы снять' : 'Не отмечен — нажмите, чтобы отметить'}
          onClick={() => toggle(flag.key)}
        >
          {flag.title}
        </button>
      ))}
      {other.map((key) => (
        <span key={key} className="chip chip--ok">
          {key.replace(/_/g, ' ')}
        </span>
      ))}
      {flags.length === 0 && (
        <span className="card__meta">не размечены — выбор оператора не оценивается</span>
      )}
      {error && <span className="alert">{error}</span>}
    </div>
  );
}

function ScenarioCard({
  scenario,
  onApprove,
  onCorrect,
  busy,
}: {
  scenario: Scenario;
  onApprove: (id: number) => void;
  onCorrect: (id: number, note: string) => void;
  busy: boolean;
}) {
  const [note, setNote] = useState('');
  const [correcting, setCorrecting] = useState(false);
  // Результат проверки грамматики держим у карточки, а не на странице:
  // замечания относятся к конкретному сценарию и должны быть рядом с ним.
  const [grammar, setGrammar] = useState<GrammarCheck | null>(null);
  const [grammarError, setGrammarError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  async function checkGrammar() {
    setChecking(true);
    setGrammar(null);
    setGrammarError(null);
    try {
      setGrammar(await teacherApi.checkGrammar(scenario.id));
    } catch (e) {
      setGrammarError(
        e instanceof Error ? e.message : 'Проверка грамматики не выполнена',
      );
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className={`draft${scenario.approved ? ' draft--approved' : ''}`}>
      <div className="draft__head">
        <div>
          <div className="draft__type">{scenario.incident_type}</div>
          <div className="card__meta">
            {scenario.address} · заявитель: {scenario.caller}
          </div>
        </div>
        <div className="draft__badges">
          <span className={scenario.is_profile ? 'chip chip--ok' : 'chip chip--warn'}>
            {scenario.is_profile ? 'профильное' : 'непрофильное'}
          </span>
          <span className="chip chip--neutral">эталон: {scenario.expected_primary_status}</span>
          {scenario.approved ? (
            <span className="chip chip--ok">утверждён</span>
          ) : (
            <span className="chip chip--danger">ждёт утверждения</span>
          )}
        </div>
      </div>

      <div className="draft__body">{scenario.description}</div>

      {scenario.required_comment_points.length > 0 && (
        <>
          <div className="card__label" style={{ marginTop: 10 }}>
            Что обязано прозвучать в комментарии
          </div>
          <ul className="draft__points">
            {scenario.required_comment_points.map((point, index) => (
              <li key={index}>{point}</li>
            ))}
          </ul>
        </>
      )}

      {Object.keys(scenario.notified_services).length > 0 && (
        <div className="draft__services">
          Оповещаются по ЕКП: {Object.keys(scenario.notified_services).join(', ')}
        </div>
      )}

      <ScenarioFlags scenario={scenario} />

      {scenario.teacher_note && (
        <div className="draft__note">Учтено замечание: {scenario.teacher_note}</div>
      )}

      {grammarError && <div className="alert">{grammarError}</div>}
      {grammar &&
        (grammar.issues.length === 0 ? (
          <div className="draft__note">
            Проверка грамматики выполнена, замечаний нет. Проверялись поля:{' '}
            {grammar.checked_fields.join(', ').toLowerCase()}.
          </div>
        ) : (
          <>
            <div className="card__label" style={{ marginTop: 10 }}>
              Замечания к грамматике
            </div>
            <ul className="draft__points">
              {grammar.issues.map((issue, index) => (
                <li key={index}>{issue}</li>
              ))}
            </ul>
          </>
        ))}

      {correcting ? (
        <>
          <textarea
            className="comment-area"
            style={{ marginTop: 10 }}
            placeholder="Что не так со сценарием? Система переформирует карточку и эталон с учётом замечания."
            value={note}
            onChange={(e) => setNote(e.target.value)}
            autoFocus
          />
          <div className="actions">
            <button
              className="btn"
              disabled={busy || note.trim().length < 3}
              onClick={() => {
                onCorrect(scenario.id, note.trim());
                setCorrecting(false);
                setNote('');
              }}
            >
              Переформировать
            </button>
            <button className="btn btn--ghost" onClick={() => setCorrecting(false)}>
              Отмена
            </button>
          </div>
        </>
      ) : (
        <div className="actions">
          {!scenario.approved && (
            <button className="btn" disabled={busy} onClick={() => onApprove(scenario.id)}>
              Утвердить
            </button>
          )}
          <button className="btn btn--ghost" disabled={busy} onClick={() => setCorrecting(true)}>
            Замечание
          </button>
          <button
            className="btn btn--ghost"
            disabled={busy || checking}
            onClick={checkGrammar}
            title="Проверить текст сценария после ручных правок. Сценарий не изменится."
          >
            {checking ? 'Проверка…' : 'Проверить грамматику'}
          </button>
        </div>
      )}
    </div>
  );
}

export function TeacherScenariosPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [group, setGroup] = useState('');
  const [count, setCount] = useState(5);
  const [difficulty, setDifficulty] = useState(2);
  const [serviceId, setServiceId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setScenarios(await api.scenarios());
  }, []);

  useEffect(() => {
    api
      .catalog()
      .then((data) => {
        setCatalog(data);
        setGroup(data.groups[0] ?? '');
        setServiceId(data.services[0]?.id ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Не удалось загрузить справочники'));
    reload().catch(() => undefined);
  }, [reload]);

  async function generate() {
    if (!group || serviceId == null) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.generate(group, count, difficulty, serviceId);
      setMessage(
        result.warning ?? `Сформировано карточек: ${result.created}. Проверьте и утвердите.`,
      );
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сформировать сценарии');
    } finally {
      setBusy(false);
    }
  }

  async function act(action: Promise<Scenario>) {
    setBusy(true);
    setError(null);
    try {
      await action;
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Операция не выполнена');
    } finally {
      setBusy(false);
    }
  }

  if (error && !catalog) return <div className="alert">{error}</div>;
  if (!catalog) return <div className="empty">Загрузка…</div>;

  const pending = scenarios.filter((s) => !s.approved).length;

  return (
    <>
      <h1 className="page-title">Учебные сценарии</h1>
      <p className="page-hint">
        Нейросеть формирует карточки, а тип происшествия и список оповещаемых служб берутся
        из классификатора. Сценарий попадает обучающимся только после вашего утверждения.
        Ждут проверки: {pending} из {scenarios.length}.
      </p>

      <div className="panel-form">
        <div className="field">
          <label htmlFor="group">Категория происшествий</label>
          <select id="group" value={group} onChange={(e) => setGroup(e.target.value)}>
            {catalog.groups.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="service">Служба обучающихся</label>
          <select
            id="service"
            value={serviceId ?? ''}
            onChange={(e) => setServiceId(Number(e.target.value))}
          >
            {catalog.services.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field field--narrow">
          <label htmlFor="count">Сколько карточек</label>
          <input
            id="count"
            type="number"
            min={1}
            max={20}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
          />
        </div>
        <div className="field field--narrow">
          <label htmlFor="difficulty">Сложность</label>
          <select
            id="difficulty"
            value={difficulty}
            onChange={(e) => setDifficulty(Number(e.target.value))}
          >
            {Object.entries(catalog.difficulties).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <button className="btn" onClick={generate} disabled={busy}>
          {busy ? 'Формирование…' : 'Сформировать'}
        </button>
      </div>

      {error && <div className="alert">{error}</div>}
      {message && <div className="pending">{message}</div>}

      {scenarios.length === 0 ? (
        <div className="empty">Сценариев пока нет. Выберите категорию и сформируйте карточки.</div>
      ) : (
        scenarios.map((scenario) => (
          <ScenarioCard
            key={scenario.id}
            scenario={scenario}
            busy={busy}
            onApprove={(id) => act(api.approveScenario(id))}
            onCorrect={(id, note) => act(api.correctScenario(id, note))}
          />
        ))
      )}
    </>
  );
}
