import { useEffect, useState } from 'react';

import { monitoringApi } from '../api/client';
import type { ErrorReport, SystemHealth } from '../api/types';

/**
 * Раздел обновляется раз в десять секунд. Чаще незачем: состояние комплекса
 * за секунду не меняется, а страница у администратора открыта часами — частый
 * опрос нагружал бы тот самый сервер, за которым он следит.
 */
const REFRESH_MS = 10_000;

const PERIODS: { hours: number; title: string }[] = [
  { hours: 1, title: 'за последний час' },
  { hours: 24, title: 'за сутки' },
  { hours: 24 * 7, title: 'за неделю' },
  { hours: 24 * 30, title: 'за месяц' },
];

function bytes(value: number | null): string {
  if (value === null) return '—';
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size >= 10 || unit === 0 ? Math.round(size) : size.toFixed(1)} ${units[unit]}`;
}

function duration(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return `${days} сут ${hours} ч`;
  if (hours) return `${hours} ч ${minutes} мин`;
  return `${minutes} мин`;
}

function moment(value: string | null): string {
  return value ? new Date(value).toLocaleString('ru-RU') : '—';
}

/** Состояние одного компонента: крупное значение, метка и объяснение. */
function Component({
  title,
  value,
  ok,
  note,
  failure,
}: {
  title: string;
  value: string;
  ok: boolean | null;
  note: string;
  failure?: string | null;
}) {
  const chip = ok === null ? 'chip chip--neutral' : ok ? 'chip chip--ok' : 'chip chip--danger';
  const label = ok === null ? 'сведений нет' : ok ? 'исправно' : 'требует внимания';
  return (
    <div className="state">
      <div className="state__head">
        <span className="state__title">{title}</span>
        <span className={chip}>{label}</span>
      </div>
      <div className="state__value">{value}</div>
      <div className="state__note">{note}</div>
      {failure && <div className="state__failure">Последняя неудача: {failure}</div>}
    </div>
  );
}

/** Шкала нагрузки. Без числа показывает причину, а не пустую полосу. */
function LoadBar({
  title,
  percent,
  value,
  note,
}: {
  title: string;
  percent: number | null;
  value: string;
  note: string;
}) {
  return (
    <div className="bar">
      <div className="bar__head">
        <span className="bar__title">{title}</span>
        <span className="bar__value">{percent === null ? 'нет данных' : `${percent} %`}</span>
      </div>
      <div className="bar__track">
        <div className="bar__fill" style={{ width: `${Math.max(percent ?? 0, 1)}%` }} />
      </div>
      <div className="state__note">
        {value}
        {value && note ? ' · ' : ''}
        {note}
      </div>
    </div>
  );
}

export function AdminSystemPage() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [report, setReport] = useState<ErrorReport | null>(null);
  const [hours, setHours] = useState(24);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<number | null>(null);

  useEffect(() => {
    // Флаг нужен, чтобы ответ, пришедший после ухода со страницы или смены
    // периода, не затирал уже показанные свежие сведения.
    let alive = true;

    async function load() {
      try {
        const [state, errors] = await Promise.all([
          monitoringApi.health(),
          monitoringApi.errors(hours),
        ]);
        if (!alive) return;
        setHealth(state);
        setReport(errors);
        setUpdatedAt(new Date());
        setError(null);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : 'Не удалось получить состояние комплекса');
      }
    }

    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [hours]);

  if (!health || !report) {
    return error ? <div className="alert">{error}</div> : <div className="empty">Загрузка…</div>;
  }

  const { cpu, memory, disk } = health.load;
  const backups = health.backups;

  return (
    <>
      <h1 className="page-title">Состояние комплекса</h1>
      <p className="page-hint">
        Раздел только показывает: настройки отсюда не меняются. Сведения обновляются
        автоматически каждые десять секунд.
      </p>
      <div className="refreshed">
        Обновлено в {updatedAt ? updatedAt.toLocaleTimeString('ru-RU') : '—'}
        {error && ` · последнее обновление не удалось: ${error}`}
      </div>

      <h2 className="section-heading">Компоненты</h2>
      <div className="state-grid">
        <Component
          title="Приложение"
          value={`работает ${duration(health.uptime_seconds)}`}
          ok={true}
          note={`Запущено ${moment(health.started_at)}. Перезапуск обнуляет этот счётчик.`}
        />
        <Component
          title="База данных"
          value={
            health.database.response_ms === null
              ? 'не отвечает'
              : `отклик ${health.database.response_ms} мс`
          }
          ok={health.database.ok}
          note={health.database.note}
        />
        <Component
          title="Языковая модель"
          value={
            health.llm.model && health.llm.model !== '—'
              ? `${health.llm.provider} · ${health.llm.model}`
              : health.llm.provider
          }
          ok={health.llm.ok}
          note={`${health.llm.note}${
            health.llm.checked_at ? ` Проверено в ${moment(health.llm.checked_at)}.` : ''
          }`}
        />
        <Component
          title="Резервные копии"
          value={
            backups.last_success_at
              ? `последняя ${moment(backups.last_success_at)}`
              : 'копий нет'
          }
          ok={backups.ok}
          note={`${backups.note}${
            backups.count !== null
              ? ` Хранится копий: ${backups.count}, размер последней ` +
                `${bytes(backups.latest_size_bytes)}.`
              : ''
          }`}
          failure={backups.last_failure}
        />
      </div>

      <h2 className="section-heading">Нагрузка на сервер</h2>
      <LoadBar
        title="Процессор"
        percent={cpu.percent}
        value={
          cpu.limit_cores
            ? `отведено ядер: ${cpu.limit_cores}`
            : 'предел по ядрам не задан'
        }
        note={`${cpu.note} Средняя очередь к процессору за минуту по серверу: ${
          cpu.load_average_1m ?? '—'
        }.`}
      />
      <LoadBar
        title="Оперативная память"
        percent={memory.percent}
        value={`${bytes(memory.used_bytes)} из ${bytes(memory.limit_bytes)} (${memory.scope})`}
        note={memory.note}
      />
      <LoadBar
        title="Диск"
        percent={disk.percent}
        value={`занято ${bytes(disk.used_bytes)} из ${bytes(disk.total_bytes)}`}
        note={disk.note}
      />

      <h2 className="section-heading">Ошибки и сбои</h2>
      <div className="field" style={{ maxWidth: 260 }}>
        <label htmlFor="период">Период</label>
        <select
          id="период"
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
        >
          {PERIODS.map((period) => (
            <option key={period.hours} value={period.hours}>
              {period.title}
            </option>
          ))}
        </select>
      </div>

      <div className="stats">
        <div className="stat">
          <div className={`stat__value ${report.total ? 'stat__value--bad' : 'stat__value--ok'}`}>
            {report.total}
          </div>
          <div className="stat__label">сбоев за период</div>
        </div>
        <div className="stat">
          <div className="stat__value">{report.groups.length}</div>
          <div className="stat__label">различных ошибок</div>
        </div>
        <div className="stat">
          <div className="stat__value">{health.errors_24h ?? '—'}</div>
          <div className="stat__label">сбоев за сутки</div>
        </div>
      </div>

      {report.total === 0 ? (
        <div className="empty">За выбранный период сбоев не было.</div>
      ) : (
        <>
          <table className="card-table">
            <thead>
              <tr>
                <th>Ошибка</th>
                <th>Сообщение</th>
                <th>Раз</th>
                <th>В последний раз</th>
              </tr>
            </thead>
            <tbody>
              {report.groups.map((group) => (
                <tr key={`${group.kind}|${group.message}`} style={{ cursor: 'default' }}>
                  <td>
                    <span className="chip chip--danger">{group.kind}</span>
                  </td>
                  <td className="card-table__address">{group.message}</td>
                  <td>{group.count}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>{moment(group.last_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2 className="section-heading">Последние записи</h2>
          <table className="card-table">
            <thead>
              <tr>
                <th>Время</th>
                <th>Запрос</th>
                <th>Ошибка</th>
                <th>Пользователь</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {report.recent.map((record) => (
                <tr key={record.id} style={{ cursor: 'default' }}>
                  <td style={{ whiteSpace: 'nowrap' }}>{moment(record.at)}</td>
                  <td className="card-table__address">
                    {record.method} {record.path}
                  </td>
                  <td className="card-table__address">
                    {record.kind}: {record.message}
                    {opened === record.id && record.traceback && (
                      <pre className="traceback">{record.traceback}</pre>
                    )}
                  </td>
                  <td>{record.actor_login ?? '—'}</td>
                  <td>
                    {record.traceback && (
                      <button
                        className="btn btn--ghost"
                        onClick={() => setOpened(opened === record.id ? null : record.id)}
                      >
                        {opened === record.id ? 'Свернуть' : 'Подробно'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="page-hint">
            Подробности нужны разработчику: назовите ему время, запрос и текст ошибки.
            Содержимое работ обучающихся в записи о сбое не попадает.
          </p>
        </>
      )}
    </>
  );
}
