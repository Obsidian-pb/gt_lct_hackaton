import { useCallback, useEffect, useRef, useState } from 'react';

import { materialsApi } from '../api/client';
import type { Material, MaterialDetail } from '../api/types';
import { formatDate, formatSize } from './MaterialsPage';

// Перечень повторяет серверный: браузер подскажет допустимое ещё в окне
// выбора файла, но решение всё равно принимает сервер — здесь это подсказка.
const ACCEPT = '.pdf,.doc,.docx,.pptx,.xlsx,.rtf,.txt,.md,.csv,.png,.jpg,.jpeg';

function MaterialEditor({
  material,
  busy,
  onSave,
  onCancel,
}: {
  material: MaterialDetail;
  busy: boolean;
  onSave: (body: { title: string; summary: string | null; body: string | null }) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(material.title);
  const [summary, setSummary] = useState(material.summary ?? '');
  const [body, setBody] = useState(material.body ?? '');

  return (
    <div className="card__block">
      <div className="field">
        <label htmlFor={`title-${material.id}`}>Название</label>
        <input
          id={`title-${material.id}`}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor={`summary-${material.id}`}>О чём материал, одной строкой</label>
        <input
          id={`summary-${material.id}`}
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
        />
      </div>
      <textarea
        className="comment-area"
        style={{ marginTop: 10, minHeight: 160 }}
        placeholder="Текст материала"
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <div className="actions">
        <button
          className="btn"
          disabled={busy || title.trim().length < 3}
          onClick={() =>
            onSave({
              title: title.trim(),
              summary: summary.trim() || null,
              body: body.trim() || null,
            })
          }
        >
          Сохранить
        </button>
        <button className="btn btn--ghost" onClick={onCancel} disabled={busy}>
          Отмена
        </button>
      </div>
    </div>
  );
}

function MaterialCard({
  material,
  busy,
  onChanged,
  onError,
  setBusy,
}: {
  material: Material;
  busy: boolean;
  onChanged: () => Promise<void>;
  onError: (message: string | null) => void;
  setBusy: (value: boolean) => void;
}) {
  const [detail, setDetail] = useState<MaterialDetail | null>(null);
  const [editing, setEditing] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function act<T>(action: Promise<T>): Promise<T | null> {
    setBusy(true);
    onError(null);
    try {
      const result = await action;
      await onChanged();
      return result;
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Операция не выполнена');
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function startEditing() {
    setBusy(true);
    try {
      setDetail(await materialsApi.read(material.id));
      setEditing(true);
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Не удалось открыть материал');
    } finally {
      setBusy(false);
    }
  }

  async function attach(file: File) {
    await act(materialsApi.upload(material.id, file));
    // Одно и то же поле выбора файла должно принимать повторную загрузку
    // того же имени — без сброса значения браузер не пришлёт событие.
    if (fileInput.current) fileInput.current.value = '';
  }

  return (
    <div className={`draft${material.published ? ' draft--approved' : ''}`}>
      <div className="draft__head">
        <div>
          <div className="draft__type">{material.title}</div>
          <div className="card__meta">
            {material.author_name} · {formatDate(material.created_at)}
          </div>
        </div>
        <div className="draft__badges">
          {material.file_name && (
            <span className="chip chip--neutral">
              {material.file_name} · {formatSize(material.size_bytes)}
            </span>
          )}
          {material.published ? (
            <span className="chip chip--ok">опубликован</span>
          ) : (
            <span className="chip chip--danger">черновик</span>
          )}
        </div>
      </div>

      {material.summary && <div className="draft__body">{material.summary}</div>}

      {!material.is_mine && (
        <div className="card__meta">Чужой материал — доступен только для чтения.</div>
      )}

      {editing && detail ? (
        <MaterialEditor
          material={detail}
          busy={busy}
          onCancel={() => setEditing(false)}
          onSave={async (body) => {
            if (await act(materialsApi.update(material.id, body))) setEditing(false);
          }}
        />
      ) : (
        <div className="actions">
          {material.is_mine && (
            <>
              {material.published ? (
                <button
                  className="btn btn--ghost"
                  disabled={busy}
                  onClick={() => act(materialsApi.unpublish(material.id))}
                >
                  Снять с публикации
                </button>
              ) : (
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => act(materialsApi.publish(material.id))}
                >
                  Опубликовать
                </button>
              )}
              <button className="btn btn--ghost" disabled={busy} onClick={startEditing}>
                Изменить
              </button>
              <button
                className="btn btn--ghost"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
              >
                {material.file_name ? 'Заменить файл' : 'Приложить файл'}
              </button>
              <input
                ref={fileInput}
                type="file"
                accept={ACCEPT}
                style={{ display: 'none' }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) attach(file).catch(() => undefined);
                }}
              />
              <button
                className="btn btn--ghost"
                disabled={busy}
                onClick={() => {
                  // Удаление материала необратимо, поэтому спрашиваем.
                  if (confirm(`Удалить материал «${material.title}»?`)) {
                    act(materialsApi.remove(material.id));
                  }
                }}
              >
                Удалить
              </button>
            </>
          )}
          {material.file_name && (
            <button
              className="btn btn--ghost"
              disabled={busy}
              onClick={() => {
                // Скачивание ничего не меняет, поэтому список не перечитываем.
                materialsApi
                  .download(material.id, material.file_name ?? `material-${material.id}`)
                  .catch((e) =>
                    onError(e instanceof Error ? e.message : 'Не удалось скачать файл'),
                  );
              }}
            >
              Скачать
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function MaterialsManagePage() {
  const [materials, setMaterials] = useState<Material[] | null>(null);
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setMaterials(await materialsApi.list());
  }, []);

  useEffect(() => {
    reload().catch((e) =>
      setError(e instanceof Error ? e.message : 'Не удалось загрузить справочную базу'),
    );
  }, [reload]);

  async function create() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await materialsApi.create({
        title: title.trim(),
        summary: summary.trim() || null,
        body: body.trim() || null,
      });
      setTitle('');
      setSummary('');
      setBody('');
      setMessage('Материал создан черновиком. Приложите файл, если нужен, и опубликуйте.');
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось создать материал');
    } finally {
      setBusy(false);
    }
  }

  if (materials === null) return <div className="empty">Загрузка…</div>;

  const drafts = materials.filter((m) => !m.published && m.is_mine).length;

  return (
    <>
      <h1 className="page-title">Справочная база</h1>
      <p className="page-hint">
        Инструкции и методические материалы для обучающихся. Материал можно написать текстом,
        приложить к нему файл или сделать и то и другое. Обучающиеся видят его только после
        публикации. Ваших черновиков: {drafts}.
      </p>

      <div className="panel-form">
        <div className="field">
          <label htmlFor="material-title">Название</label>
          <input
            id="material-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Например: Порядок приёма вызова о ДТП"
          />
        </div>
        <div className="field">
          <label htmlFor="material-summary">О чём материал, одной строкой</label>
          <input
            id="material-summary"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
          />
        </div>
        <button className="btn" onClick={create} disabled={busy || title.trim().length < 3}>
          {busy ? 'Сохранение…' : 'Создать'}
        </button>
      </div>

      <textarea
        className="comment-area"
        style={{ minHeight: 120 }}
        placeholder="Текст материала. Можно оставить пустым, если весь материал — в приложенном файле."
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />

      {error && <div className="alert">{error}</div>}
      {message && <div className="pending">{message}</div>}

      {materials.length === 0 ? (
        <div className="empty">Справочная база пуста. Создайте первый материал.</div>
      ) : (
        materials.map((material) => (
          <MaterialCard
            key={material.id}
            material={material}
            busy={busy}
            setBusy={setBusy}
            onChanged={reload}
            onError={setError}
          />
        ))
      )}
    </>
  );
}
