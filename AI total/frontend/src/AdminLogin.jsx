import {useState} from 'react';
import {signInAdmin} from './admin-auth.js';

export default function AdminLogin(){
 const [login,setLogin]=useState(''),[password,setPassword]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const submit=async e=>{e.preventDefault();setError('');if(!login.trim())return setError('Укажите логин.');if(!password)return setError('Укажите пароль.');
  setBusy(true);try{await signInAdmin(login.trim(),password);location.assign('/admin');}catch(err){setError(err.message||'Не удалось войти.');}finally{setBusy(false);}};
 return <main className="admin-login-page"><section className="admin-login-card"><a className="admin-login-back" href="/">← На главную</a><div className="admin-login-mark">112</div><p className="admin-login-eyebrow">Административный контур</p><h1>Вход администратора</h1><p className="admin-login-copy">Учётная запись проверяется сервером. По умолчанию: admin / admin123 (смените пароль после первого входа).</p><form onSubmit={submit}><label>Логин<input autoFocus value={login} onChange={e=>setLogin(e.target.value)} maxLength={64} autoComplete="username" placeholder="admin"/></label><label>Пароль<input type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password"/></label>{error&&<p className="admin-login-error" role="alert">{error}</p>}<button className="admin-login-submit" disabled={busy}>{busy?'Подождите…':'Войти'}</button></form><small>Аутентификация по JWT на сервере; данные не хранятся в браузере.</small></section></main>;
}
