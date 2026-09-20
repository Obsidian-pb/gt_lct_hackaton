import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import { groupsApi } from '../api/client';
import type { SessionMember, StudyGroup } from '../api/types';

/**
 * Учебные группы — постоянные списки обучающихся.
 *
 * Техническое задание требует от преподавателя назначать учащимся «конкретные
 * задания и группы». Задания назначаются составом занятия, а группа избавляет
 * от того, чтобы собирать одних и тех же людей заново к каждому занятию.
 *
 * В занятие состав попадает копированием: правка группы через неделю
 * не переписывает уже проведённое занятие.
 */
function StudentPicker({
  students,
  chosen,
  onToggle,
}: {
  students: SessionMember[];
  chosen: Set<number>;
  onToggle: (id: number) => void;
}) {
  return (
    <div className="picker">
      {students.map((student) => (
        <label key={student.id} className="picker__row">
          <input
            type="checkbox"
            checked={chosen.has(student.id)}
            onChange={() => onToggle(student.id)}
          />
          <span>{student.full_name}</span>
          <span className="card__meta">{student.service ?? 'без службы'}</span>
        </label>
      ))}
      {students.length === 0 && <div className="empty">Обучающихся пока нет</div>}
    </div>
  );
}

export function TeacherGroupsPage() {
  const [groups, setGroups] = useState<StudyGroup[]>([]);
  const [students, setStudents] = useState<SessionMember[]>([]);
  const [title, setTitle] = useState('');
  const [note, setNote] = useState('');
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    setGroups(await groupsApi.list());
  }, []);

  useEffect(() => {
    reload().catch((e) => setError(e instanceof Error ? e.message : 'Не удалось загрузить группы'));
    api.sessionStudents().then(setStudents).catch(() => undefined);
  }, [reload]);

  const toggle = useCallback((id: number) => {
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    setEditing(null);
    setTitle('');
    setNote('');
    setChosen(new Set());
  }, []);

  const save = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const body = { title, note: note || null, student_ids: [...chosen] };
      if (editing === null) await groupsApi.create(body);
      else await groupsApi.update(editing, body);
      await reload();
      reset();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить группу');
    } finally {
      setBusy(false);
    }
  }, [title, note, chosen, editing, reload, reset]);

  const edit = useCallback((group: StudyGroup) => {
    setEditing(group.id);
    setTitle(group.title);
    setNote(group.note ?? '');
    setChosen(new Set(group.students.map((s) => s.id)));
  }, []);

  const remove = useCallback(
    async (group: StudyGroup) => {
      // Состав проведённых занятий не пострадает — он был скопирован,
      // а не связан ссылкой. Об этом сказано прямо, иначе преподаватель
      // побоится удалять устаревшие группы.
      if (!window.confirm(`Удалить группу «${group.title}»? Проведённые занятия останутся как есть.`))
        return;
      await groupsApi.remove(group.id);
      await reload();
      if (editing === group.id) reset();
    },
    [reload, editing, reset],
  );

  return (
    <>
      <div className="card">
        <div className="card__block">
          <div className="card__label">
            {editing === null ? 'Новая учебная группа' : 'Правка группы'}
          </div>

          <div className="field" style={{ maxWidth: 460, marginTop: 8 }}>
            <label htmlFor="group-title">Название</label>
            <input
              id="group-title"
              value={title}
              placeholder="Например: Смена А, набор сентября"
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="field" style={{ maxWidth: 460 }}>
            <label htmlFor="group-note">Примечание</label>
            <input
              id="group-note"
              value={note}
              placeholder="Необязательно"
              onChange={(e) => setNote(e.target.value)}
            />
          </div>

          <div className="card__label" style={{ marginTop: 12 }}>
            Состав — {chosen.size} из {students.length}
          </div>
          <StudentPicker students={students} chosen={chosen} onToggle={toggle} />

          {error && <div className="alert" style={{ marginTop: 10 }}>{error}</div>}

          <div className="actions">
            <button className="btn" onClick={save} disabled={busy || title.trim().length < 3}>
              {busy ? 'Сохранение…' : editing === null ? 'Создать группу' : 'Сохранить'}
            </button>
            {editing !== null && (
              <button className="btn btn--ghost" onClick={reset}>
                Отменить правку
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card__block">
          <div className="card__label">Учебные группы</div>
          {groups.length === 0 && (
            <div className="empty">
              Групп пока нет. Соберите первую — и состав занятия будет заполняться одним выбором.
            </div>
          )}
          {groups.map((group) => (
            <div key={group.id} className="group">
              <div className="group__head">
                <b>{group.title}</b>
                <span className="chip chip--neutral">{group.students.length} чел.</span>
                <div className="app-header__spacer" />
                <button className="btn btn--ghost" onClick={() => edit(group)}>
                  Править
                </button>
                <button className="btn btn--ghost" onClick={() => remove(group)}>
                  Удалить
                </button>
              </div>
              {group.note && <div className="card__meta">{group.note}</div>}
              <div className="card__meta">
                {group.students.map((s) => s.full_name).join(', ') || 'состав пуст'}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
