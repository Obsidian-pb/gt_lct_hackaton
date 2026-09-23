import { useCallback, useEffect, useRef, useState } from 'react';

import { classifierApi } from '../api/client';
import type { ClassifierState, ClassifierVersion } from '../api/types';

/**
 * Редакции Единого классификатора происшествий.
 *
 * Механизм импорта обновлений учебных материалов из ТЗ. Классификатор
 * правится не реже раза в год: администратор загружает исходный xlsx новой
 * редакции, видит число правил и предупреждения разбора, а потом включает её.
 * Включённая редакция достаётся занятиям, созданным после включения; уже
 * созданные остаются на своей — иначе отчёт разошёлся бы с тем, что
 * обучающийся видел на экране.
 */

function moment(value: string): string {
  return new Date(value).toLocaleString('ru-RU');
}

function UploadForm({ onUploaded }: { onUploaded: (v: ClassifierVersion) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [label, setLabel] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const uploaded = await classifierApi.upload(file, label.trim(), note);
      setFile(null);
      setLabel('');
      setNote('');
      if (fileInput.current) fileInput.current.value = '';
      onUploaded(uploaded);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить редакцию');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="panel-form">
        <div className="field">
          <label htmlFor="classifier-file">Файл классификатора (.xlsx)</label>
          <input
            id="classifier-file"
            ref={fileInput}
            type="file"
            accept=".xlsx"
            onChange={(e) => {
              const chosen = e.target.files?.[0] ?? null;
              setFile(chosen);
              // Имя файла как обозначение по умолчанию: обычно в нём и есть
              // год или номер редакции, а править его проще, чем печатать.
              if (chosen && !label) setLabel(chosen.name.replace(/\.xlsx$/i, '').slice(0, 64));
            }}
          />
        </div>
        <div className="field field--narrow">
          <label htmlFor="classifier-label">Обозначение редакции</label>
          <input
            id="classifier-label"
            value={label}
            maxLength={64}
            placeholder="ЕКП 2027"
            onChange={(e) => setLabel(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="classifier-note">Примечание</label>
          <input
            id="classifier-note"
            value={note}
            maxLength={500}
            placeholder="откуда получена, что изменилось"
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        <button className="btn" onClick={submit} disabled={busy || !file || !label.trim()}>
          {busy ? 'Разбор файла…' : 'Загрузить редакцию'}
        </button>
      </div>
      <p className="page-hint">
        Принимается исходная книга Excel в том виде, в каком её выдаёт ГБУ «Система 112».
        Файл разбирается сразу; если он не читается как классификатор, ничего не сохраняется.
        Загруженная редакция не включается сама — сначала проверьте число правил
        и предупреждения.
      </p>
      {error && <div className="alert">{error}</div>}
    </>
  );
}

export function AdminClassifierPage() {
  const [state, setState] = useState<ClassifierState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    setState(await classifierApi.read());
  }, []);

  useEffect(() => {
    reload().catch((e) =>
      setError(e instanceof Error ? e.message : 'Не удалось загрузить список редакций'),
    );
  }, [reload]);

  async function act(action: () => Promise<ClassifierState>, done: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setState(await action());
      setNotice(done);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Операция не выполнена');
    } finally {
      setBusy(false);
    }
  }

  if (error && !state) return <div className="alert">{error}</div>;
  if (!state) return <div className="empty">Загрузка редакций…</div>;

  return (
    <>
      <h1 className="page-title">Классификатор происшествий</h1>
      <p className="page-hint">
        Единый классификатор задаёт эталон: итоговый тип происшествия и список оповещаемых
        служб. Включённая редакция действует для новых занятий и для подготовки сценариев.
        Занятие держится редакции, которая была включена при его создании, — уже проведённые
        занятия смена редакции не затрагивает.
      </p>

      <h2 className="section-heading">Загрузить новую редакцию</h2>
      <UploadForm
        onUploaded={(uploaded) => {
          setWarnings(uploaded.warnings);
          setNotice(
            `Редакция «${uploaded.label}» загружена: правил ${uploaded.rule_count}. `
              + 'Она пока не включена.',
          );
          reload().catch(() => undefined);
        }}
      />

      {notice && !error && <div className="draft__note">{notice}</div>}
      {error && <div className="alert">{error}</div>}
      {warnings.length > 0 && (
        <div className="alert">
          Разбор не распознал подколонки списка оповещения: {warnings.join('; ')}. Такие
          столбцы не применяются ни при каких признаках опросной карты. Если это новые признаки
          классификатора, сообщите разработчику — их нужно добавить в разбор.
        </div>
      )}

      <h2 className="section-heading">Редакции</h2>
      <table className="card-table">
        <thead>
          <tr>
            <th>Обозначение</th>
            <th>Исходный файл</th>
            <th>Правил</th>
            <th>Загружена</th>
            <th>Состояние</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr style={{ cursor: 'default' }}>
            <td>
              <div className="card-table__type">Встроенная</div>
              <div className="card-table__address">редакция из файла поставки</div>
            </td>
            <td className="card-table__address">{state.builtin_source}</td>
            <td>{state.builtin_rule_count}</td>
            <td className="card-table__address">вместе с комплексом</td>
            <td>
              <span className={state.builtin_active ? 'chip chip--ok' : 'chip chip--neutral'}>
                {state.builtin_active ? 'действует' : 'не действует'}
              </span>
            </td>
            <td>
              {!state.builtin_active && (
                <button
                  className="btn btn--ghost"
                  disabled={busy}
                  onClick={() =>
                    act(
                      () => classifierApi.restoreBuiltin(),
                      'Комплекс вернулся к встроенной редакции. Новые занятия пойдут по ней.',
                    )
                  }
                >
                  Вернуться к встроенной
                </button>
              )}
            </td>
          </tr>
          {state.versions.map((version) => (
            <tr key={version.id} style={{ cursor: 'default' }}>
              <td>
                <div className="card-table__type">{version.label}</div>
                {version.note && <div className="card-table__address">{version.note}</div>}
              </td>
              <td className="card-table__address" title={`sha256 ${version.sha256}`}>
                {version.source_name}
              </td>
              <td>{version.rule_count}</td>
              <td className="card-table__address">
                {moment(version.uploaded_at)}
                <br />
                {version.uploaded_by}
              </td>
              <td>
                <span className={version.is_active ? 'chip chip--ok' : 'chip chip--neutral'}>
                  {version.is_active ? 'действует' : 'выключена'}
                </span>
              </td>
              <td>
                {!version.is_active && (
                  <button
                    className="btn btn--ghost"
                    disabled={busy}
                    onClick={() =>
                      act(
                        () => classifierApi.activate(version.id),
                        `Редакция «${version.label}» включена. Новые занятия пойдут по ней.`,
                      )
                    }
                  >
                    Включить
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {state.versions.length === 0 && (
        <p className="page-hint">
          Загруженных редакций нет: комплекс работает по встроенной редакции.
        </p>
      )}
    </>
  );
}
