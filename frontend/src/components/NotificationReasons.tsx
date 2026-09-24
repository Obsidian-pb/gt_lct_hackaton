import type { NotificationReason } from '../api/types';

/**
 * Обоснование списка оповещения.
 *
 * Сам список учит мало: обучающийся видит «МВД, СМП, ЦЭМП» и не понимает,
 * откуда взялась скорая. Здесь каждая служба связана с признаком опросной
 * карты: «СМП — потому что отмечены пострадавшие». Отдельно, приглушённо, —
 * службы, которых в списке нет, но которые добавил бы признак: это и есть
 * урок о том, что список выводится из признаков, а не запоминается.
 */
export function NotificationReasons({ reasons }: { reasons: NotificationReason[] }) {
  if (reasons.length === 0) return null;
  const notified = reasons.filter((r) => r.notified);
  const conditional = reasons.filter((r) => !r.notified);
  return (
    <div className="reasons">
      {notified.length > 0 && (
        <>
          <div className="card__label">Почему эти службы в списке</div>
          <ul className="reasons__list">
            {notified.map((r) => (
              <li key={r.service}>
                <b>{r.service}</b> <span className="card__meta">({r.incident_type})</span> —{' '}
                {r.reason}
              </li>
            ))}
          </ul>
        </>
      )}
      {conditional.length > 0 && (
        <>
          <div className="card__label" style={{ marginTop: 8 }}>
            Не оповещаются в этом вызове
          </div>
          <ul className="reasons__list reasons__list--off">
            {conditional.map((r) => (
              <li key={r.service}>
                <b>{r.service}</b> — {r.reason}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
