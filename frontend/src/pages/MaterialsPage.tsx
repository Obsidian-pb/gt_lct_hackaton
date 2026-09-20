import { useCallback, useEffect, useState } from 'react';

import { materialsApi } from '../api/client';
import type { Material, MaterialDetail } from '../api/types';

/** Размер вложения по-человечески: «2,4 МБ» читается, а «2517184» — нет. */
export function formatSize(bytes: number | null): string {
  if (bytes === null) return '';
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} МБ`;
}

export function formatDate(value: string): string {
  return new Date(value).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

function MaterialRow({
  material,
  onError,
}: {
  material: Material;
  onError: (message: string) => void;
}) {
  const [detail, setDetail] = useState<MaterialDetail | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  // Текст подгружается по требованию: в списке его нет, а держать открытыми
  // сразу все методички всё равно незачем.
  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (detail) return;
    setBusy(true);
    try {
      setDetail(await materialsApi.read(material.id));
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Не удалось открыть материал');
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    try {
      await materialsApi.download(material.id, material.file_name ?? `material-${material.id}`);
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Не удалось скачать файл');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="draft">
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
              файл · {formatSize(material.size_bytes)}
            </span>
          )}
        </div>
      </div>

      {material.summary && <div className="draft__body">{material.summary}</div>}

      {open && (
        <div className="card__block">
          {busy && !detail ? (
            <div className="empty">Загрузка…</div>
          ) : detail?.body ? (
            // Текст методички хранится как есть, с авторскими переносами строк.
            <div className="card__description" style={{ whiteSpace: 'pre-wrap' }}>
              {detail.body}
            </div>
          ) : (
            <div className="card__meta">Текста нет — материал целиком в приложенном файле.</div>
          )}
        </div>
      )}

      <div className="actions">
        <button className="btn btn--ghost" onClick={toggle} disabled={busy}>
          {open ? 'Свернуть' : 'Читать'}
        </button>
        {material.file_name && (
          <button className="btn" onClick={save} disabled={busy}>
            Скачать «{material.file_name}»
          </button>
        )}
      </div>
    </div>
  );
}

export function MaterialsPage() {
  const [materials, setMaterials] = useState<Material[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setMaterials(await materialsApi.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить справочную базу');
      setMaterials([]);
    }
  }, []);

  useEffect(() => {
    reload().catch(() => undefined);
  }, [reload]);

  if (materials === null) return <div className="empty">Загрузка…</div>;

  return (
    <>
      <h1 className="page-title">Справочная база</h1>
      <p className="page-hint">
        Инструкции и методические материалы, подготовленные преподавателями. Материалы можно
        читать и во время занятия: смотреть в памятку — не нарушение, а рабочая привычка.
      </p>

      {error && <div className="alert">{error}</div>}

      {materials.length === 0 ? (
        <div className="empty">Материалов пока нет.</div>
      ) : (
        materials.map((material) => (
          <MaterialRow key={material.id} material={material} onError={setError} />
        ))
      )}
    </>
  );
}
