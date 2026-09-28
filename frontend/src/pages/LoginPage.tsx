import { useState } from 'react';
import type { FormEvent } from 'react';

import { api, login } from '../api/client';
import { useAuth } from '../auth';

export function LoginPage() {
  const { signIn } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      signIn(await api.me());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось войти');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form className="login__box" onSubmit={submit}>
        <img className="login__logo" src="/hero-logo.svg" alt="112" />
        <h1 className="login__title">Учебный комплекс АРМ-112</h1>
        <p className="login__sub">
          Подготовка операторов Службы 112 и диспетчеров дежурно-диспетчерских служб
        </p>

        {error && <div className="alert">{error}</div>}

        <div className="field">
          <label htmlFor="login">Логин</label>
          <input
            id="login"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            autoComplete="username"
          />
        </div>
        <div className="field">
          <label htmlFor="password">Пароль</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>

        <button className="btn" style={{ width: '100%' }} disabled={busy}>
          {busy ? 'Проверка…' : 'Войти'}
        </button>

        <p className="login__hint">
          Учебный стенд. Демонстрационные учётные записи: <b>student</b>, <b>teacher</b> —
          пароль совпадает с логином.
        </p>
      </form>
    </div>
  );
}
