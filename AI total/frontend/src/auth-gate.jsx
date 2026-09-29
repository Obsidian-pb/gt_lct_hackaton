/* Minimal role gate for student/teacher/cards pages (Этап 5: RBAC).
   Reuses the server JWT flow of admin-auth.js; keeps the token in
   sessionStorage so /api/v1 calls carry Authorization: Bearer. */
import React, {useState} from 'react';
import {attachToken} from './api.js';
import {adminSignedIn, signInAdmin, accessToken} from './admin-auth.js';

function claims(token) {
  try {
    const part = token.split('.')[1];
    const pad = '='.repeat((4 - part.length % 4) % 4);
    return JSON.parse(decodeURIComponent(escape(
      atob(part.replace(/-/g, '+').replace(/_/g, '/') + pad))));
  } catch { return null; }
}

function LoginForm({role, onSuccess}) {
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  async function submit(event) {
    event.preventDefault();
    setError('');
    try {
      const user = await signInAdmin(login.trim(), password);
      if (!user || !['admin', 'teacher', 'student'].includes(user.role)) {
        throw new Error('Учётная запись недоступна.');
      }
      attachToken(accessToken());
      onSuccess(user);
    } catch (exc) {
      setError(exc.message || 'Не удалось войти.');
    }
  }
  return (
    <div className="auth-gate">
      <form className="auth-gate-form" onSubmit={submit}>
        <h2>Вход в учебный симулятор</h2>
        <p className="muted">Требуется роль: {role}</p>
        <input value={login} onChange={e => setLogin(e.target.value)}
               placeholder="Логин" autoComplete="username" required />
        <input type="password" value={password}
               onChange={e => setPassword(e.target.value)}
               placeholder="Пароль" autoComplete="current-password" required />
        {error && <div className="auth-error">{error}</div>}
        <button type="submit">Войти</button>
      </form>
    </div>
  );
}

export default function RequireRole({role, children}) {
  const [user, setUser] = useState(() => {
    if (!adminSignedIn()) return null;
    const token = accessToken();
    const data = claims(token);
    if (!data || (role && data.role !== role && data.role !== 'admin')) return null;
    attachToken(token);
    return data;
  });
  if (!user) {
    return <LoginForm role={role || 'пользователь'}
                      onSuccess={setUser} />;
  }
  return children;
}