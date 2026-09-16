import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { Call } from '../api/types';

export function OperatorCallsPage() {
  const navigate = useNavigate();
  const [calls, setCalls] = useState<Call[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .myCalls()
      .then(setCalls)
      .catch((e) => setError(e instanceof Error ? e.message : 'Не удалось загрузить вызовы'));
  }, []);

  if (error) return <div className="alert">{error}</div>;
  if (!calls) return <div className="empty">Загрузка…</div>;
  if (calls.length === 0) {
    return <div className="empty">Учебных вызовов пока нет.</div>;
  }

  const pending = calls.filter((c) => !c.finished).length;

  return (
    <>
      <h1 className="page-title">Приём вызовов</h1>
      <p className="page-hint">
        Выслушайте заявителя, классифицируйте происшествие по опросной карте и зарегистрируйте
        карточку. От выбранных признаков зависит итоговый тип происшествия, а значит — какие
        службы получат информацию. В работе: {pending} из {calls.length}.
      </p>

      <table className="card-table">
        <thead>
          <tr>
            <th style={{ width: '60%' }}>Сообщение заявителя</th>
            <th>Заявитель</th>
            <th>Состояние</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((call) => (
            <tr key={call.attempt_id} onClick={() => navigate(`/calls/${call.attempt_id}`)}>
              <td>
                <div className="card-table__type">{call.legend}</div>
                <div className="card-table__address">{call.reported_address}</div>
              </td>
              <td className="card-table__address">{call.caller}</td>
              <td>
                {call.finished ? (
                  <span className="chip chip--ok">обработан</span>
                ) : (
                  <span className="chip chip--warn">ожидает</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
