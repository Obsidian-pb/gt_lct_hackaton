import { useEffect, useState } from 'react';

import { settingsApi } from '../api/client';
import type { LlmSettings, LlmTestResult, LoggingSettings, SystemSettings } from '../api/types';

/**
 * Конфигурация комплекса: языковая модель и параметры журналирования.
 *
 * Требования ТЗ к роли администратора — «управлять настройками безопасности
 * и политиками доступа» и «конфигурировать параметры журналирования». Но
 * главная причина раздела приземлённее: комплекс должен работать и в
 * изолированном контуре с локальной моделью, и с внешним API, а переключение
 * правкой файла `.env` с перезапуском контейнера администратору учебного
 * комплекса недоступно — у него есть только браузер.
 */
const PROVIDER_LABELS: Record<string, string> = {
  stub: 'Без модели — только детерминированные проверки',
  local: 'Локальная модель (Ollama, vLLM, llama.cpp)',
  openai: 'Внешний OpenAI-совместимый API',
  gigachat: 'GigaChat (Сбер)',
};

const LEVEL_LABELS: Record<string, string> = {
  ERROR: 'Только ошибки',
  WARNING: 'Ошибки и предупреждения',
  INFO: 'Обычная подробность',
  DEBUG: 'Подробно — для разбора сбоя',
};

/**
 * Уходят ли тексты обучающихся за пределы комплекса.
 *
 * Та же проверка, что и на сервере, но считается прямо в форме: предупреждение
 * должно появляться при выборе провайдера, до сохранения, — иначе о нём
 * узнавали бы уже после того, как настройка подействовала.
 */
function isExternal(provider: string, baseUrl: string): boolean {
  if (provider === 'stub') return false;
  if (provider === 'gigachat') return true;
  let host = '';
  try {
    host = new URL(baseUrl).hostname;
  } catch {
    // Недописанный адрес внешним контуром считать рано.
    return false;
  }
  if (host === 'localhost' || host === 'host.docker.internal' || host === '::1') return true;
  return /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host);
}

function formatWho(at: string | null, by: string | null): string {
  if (!at) return 'значение из переменных окружения, из интерфейса не менялось';
  return `изменено ${new Date(at).toLocaleString('ru-RU')}${by ? `, ${by}` : ''}`;
}

function LlmForm({
  value,
  providers,
  onSaved,
}: {
  value: LlmSettings;
  providers: string[];
  onSaved: (s: LlmSettings) => void;
}) {
  const [provider, setProvider] = useState(value.provider);
  const [baseUrl, setBaseUrl] = useState(value.base_url);
  const [model, setModel] = useState(value.model);
  const [apiKey, setApiKey] = useState('');
  const [keySet, setKeySet] = useState(value.api_key_set);
  const [disableThinking, setDisableThinking] = useState(value.disable_thinking);
  const [test, setTest] = useState<LlmTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const body = {
    provider,
    base_url: baseUrl,
    model,
    api_key: apiKey,
    disable_thinking: disableThinking,
  };
  const external = isExternal(provider, baseUrl);
  const needsAddress = provider === 'local' || provider === 'openai';
  const needsModel = provider !== 'stub';

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Операция не выполнена');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="panel-form">
        <div className="field">
          <label htmlFor="provider">Провайдер языковой модели</label>
          <select
            id="provider"
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setTest(null);
            }}
          >
            {providers.map((key) => (
              <option key={key} value={key}>
                {PROVIDER_LABELS[key] ?? key}
              </option>
            ))}
          </select>
        </div>

        {needsAddress && (
          <div className="field">
            <label htmlFor="base-url">Адрес API (оканчивается на /v1)</label>
            <input
              id="base-url"
              value={baseUrl}
              placeholder="http://127.0.0.1:8095/v1"
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </div>
        )}

        {needsModel && (
          <div className="field">
            <label htmlFor="model">Имя модели</label>
            <input
              id="model"
              value={model}
              placeholder="qwen3-coder"
              onChange={(e) => setModel(e.target.value)}
            />
          </div>
        )}

        {needsModel && (
          <div className="field">
            <label htmlFor="api-key">
              Ключ доступа {keySet ? '(задан)' : '(не задан)'}
            </label>
            <input
              id="api-key"
              type="password"
              value={apiKey}
              autoComplete="new-password"
              placeholder={keySet ? 'оставьте пустым, чтобы не менять' : 'ключ не задан'}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
        )}

        {provider !== 'gigachat' && needsModel && (
          <div className="field">
            <label htmlFor="thinking">Рассуждающие модели</label>
            <label className="picker__row" htmlFor="thinking">
              <input
                id="thinking"
                type="checkbox"
                checked={disableThinking}
                onChange={(e) => setDisableThinking(e.target.checked)}
              />
              <span>Отключить «размышление» (Qwen3 и подобные)</span>
            </label>
          </div>
        )}

        <button
          className="btn btn--ghost"
          disabled={busy}
          onClick={() => run(async () => setTest(await settingsApi.testLlm(body)))}
        >
          Проверить связь
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() =>
            run(async () => {
              const result = await settingsApi.saveLlm(body);
              // Ключ обратно не приходит — очищаем поле, чтобы следующее
              // сохранение не приняло старый ввод за новый ключ.
              setApiKey('');
              setKeySet(result.api_key_set);
              setSaved(true);
              onSaved(result);
            })
          }
        >
          Сохранить
        </button>
        {keySet && (
          <button
            className="btn btn--ghost"
            disabled={busy}
            onClick={() =>
              run(async () => {
                // Ключ негде подсмотреть заново, поэтому стирание подтверждается:
                // случайное нажатие оставило бы комплекс без доступа к модели.
                if (
                  !window.confirm(
                    'Стереть ключ доступа к модели? Восстановить его можно будет '
                      + 'только вводом заново.',
                  )
                )
                  return;
                const result = await settingsApi.clearLlmKey();
                setKeySet(result.api_key_set);
                onSaved(result);
              })
            }
          >
            Стереть ключ
          </button>
        )}
      </div>

      {needsModel && (
        <p className="page-hint">
          Ключ доступа не показывается ни здесь, ни где-либо ещё: комплекс отдаёт только
          признак «задан». Пустое поле означает «не менять» — чтобы правка адреса случайно
          не стирала ключ. Для стирания есть отдельная кнопка.
        </p>
      )}

      {external && (
        <div className="alert">
          Выбран внешний контур. Тексты, которые вводят обучающиеся, — комментарии
          к статусам реагирования и описания происшествий — будут отправляться за пределы
          учебного комплекса, поставщику модели. Для изолированного контура выбирайте
          локальную модель или режим без модели.
        </div>
      )}

      {test && (
        <div className={test.ok ? 'draft__note' : 'alert'}>
          {test.ok ? 'Связь есть. ' : 'Связи нет. '}
          {test.detail}
        </div>
      )}

      {saved && !error && (
        <div className="draft__note">
          Настройка сохранена и действует сразу — перезапуск комплекса не нужен.
        </div>
      )}
      {error && <div className="alert">{error}</div>}
    </>
  );
}

function LoggingForm({
  value,
  onSaved,
}: {
  value: LoggingSettings;
  onSaved: (s: LoggingSettings) => void;
}) {
  const [days, setDays] = useState(String(value.audit_retention_days));
  const [level, setLevel] = useState(value.level);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const result = await settingsApi.saveLogging({
        audit_retention_days: Number(days),
        level,
      });
      setSaved(true);
      onSaved(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить параметры');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="panel-form">
        <div className="field field--narrow">
          <label htmlFor="retention">Глубина хранения журнала аудита, суток</label>
          <input
            id="retention"
            type="number"
            min={value.min_audit_retention_days}
            value={days}
            onChange={(e) => setDays(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="level">Подробность журнала приложения</label>
          <select id="level" value={level} onChange={(e) => setLevel(e.target.value)}>
            {value.levels.map((item) => (
              <option key={item} value={item}>
                {LEVEL_LABELS[item] ?? item}
              </option>
            ))}
          </select>
        </div>
        <button className="btn" onClick={submit} disabled={busy || !days}>
          Сохранить
        </button>
      </div>

      <p className="page-hint">
        Меньше {value.min_audit_retention_days} суток задать нельзя: техническое задание
        требует хранить журнал безопасности не менее шести месяцев. Записи журнала комплекс
        не удаляет сам — значение задаёт срок, раньше которого их нельзя удалять при
        обслуживании базы.
      </p>

      {saved && !error && <div className="draft__note">Параметры сохранены.</div>}
      {error && <div className="alert">{error}</div>}
    </>
  );
}

export function AdminSettingsPage() {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    settingsApi
      .read()
      .then(setSettings)
      .catch((e) =>
        setError(e instanceof Error ? e.message : 'Не удалось загрузить конфигурацию'),
      );
  }, []);

  if (error) return <div className="alert">{error}</div>;
  if (!settings) return <div className="empty">Загрузка конфигурации…</div>;

  return (
    <>
      <h1 className="page-title">Конфигурация</h1>
      <p className="page-hint">
        Значения из этого раздела главнее переменных окружения: переменные задают начальное
        состояние при первом запуске, дальше комплексом управляет администратор. Каждое
        изменение записывается в журнал аудита.
      </p>

      <h2 className="section-heading">Языковая модель</h2>
      <p className="page-hint">
        Модель выполняет смысловой разбор комментариев обучающихся и подготовку учебных
        сценариев. {formatWho(settings.llm.updated_at, settings.llm.updated_by)}.
      </p>
      <LlmForm
        value={settings.llm}
        providers={settings.providers}
        onSaved={(llm) => setSettings({ ...settings, llm })}
      />

      <h2 className="section-heading">Журналирование</h2>
      <p className="page-hint">
        {formatWho(settings.logging.updated_at, settings.logging.updated_by)}.
      </p>
      <LoggingForm
        value={settings.logging}
        onSaved={(logging) => setSettings({ ...settings, logging })}
      />
    </>
  );
}
