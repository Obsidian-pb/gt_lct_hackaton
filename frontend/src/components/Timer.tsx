import { useEffect, useState } from 'react';

interface Props {
  /** Момент направления карточки в службу — от него отсчитывается норматив. */
  issuedAt: string;
  deadlineSeconds: number;
  /** Секунды на момент остановки: у завершённой карточки таймер замирает. */
  frozenAt?: number | null;
}

function elapsedSince(issuedAt: string): number {
  return (Date.now() - new Date(issuedAt).getTime()) / 1000;
}

export function Timer({ issuedAt, deadlineSeconds, frozenAt }: Props) {
  const [elapsed, setElapsed] = useState(() => elapsedSince(issuedAt));

  useEffect(() => {
    if (frozenAt != null) return;
    const id = setInterval(() => setElapsed(elapsedSince(issuedAt)), 250);
    return () => clearInterval(id);
  }, [issuedAt, frozenAt]);

  const value = frozenAt ?? elapsed;
  const level = value > deadlineSeconds ? 'over' : value > deadlineSeconds * 0.7 ? 'soon' : 'ok';

  return (
    <div className={`timer timer--${level}`} title="Норматив подтверждения приёма карточки">
      <span className="timer__value">{value.toFixed(1)} с</span>
      <span className="timer__limit">из {deadlineSeconds} с</span>
    </div>
  );
}
