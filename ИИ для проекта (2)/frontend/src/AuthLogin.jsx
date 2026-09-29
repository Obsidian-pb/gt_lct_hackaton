import {useMemo,useState} from 'react';

const ROLES={
 admin:{label:'Администратор',eyebrow:'Административный контур',home:'/admin'},
 teacher:{label:'Преподаватель',eyebrow:'Учебный контур',home:'/teacher'},
 student:{label:'Обучающийся',eyebrow:'Учебный контур',home:'/student'},
};

function safeNext(value){return typeof value==='string'&&/^\/(admin|teacher|student|cards|training|scenarios)(?:$|[?#])/.test(value)?value:'';}

export default function AuthLogin(){
 const query=useMemo(()=>new URLSearchParams(location.search),[]);
 const requested=ROLES[query.get('role')]?query.get('role'):'student';
 const [role,setRole]=useState(requested),[login,setLogin]=useState(''),[password,setPassword]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const info=ROLES[role];
 const submit=async event=>{event.preventDefault();if(busy)return;setBusy(true);setError('');
  try{
   const response=await fetch('/api/v1/auth/login',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({login:login.trim(),password,role})});
   let body={};try{body=await response.json();}catch{}
   if(!response.ok)throw new Error(body?.error?.message||'Не удалось войти.');
   const user=body?.data?.user;
   if(!user)throw new Error('Сервер не вернул данные пользователя.');
   const next=safeNext(query.get('next'));
   location.assign(next||body.data.home||ROLES[user.role]?.home||'/');
  }catch(e){setError(e.message||'Не удалось войти.');setBusy(false);}
 };
 return <main className="admin-login-page"><section className="admin-login-card"><a className="admin-login-back" href="/">← На главную</a><div className="admin-login-mark">112</div><p className="admin-login-eyebrow">{info.eyebrow}</p><h1>Вход · {info.label}</h1><p className="admin-login-copy">Введите логин и пароль, которые выдал администратор системы.</p><form onSubmit={submit}><label>Роль<select value={role} onChange={e=>setRole(e.target.value)}><option value="teacher">Преподаватель</option><option value="student">Обучающийся</option><option value="admin">Администратор</option></select></label><label>Логин<input autoFocus value={login} onChange={e=>setLogin(e.target.value)} maxLength={64} autoComplete="username" required/></label><label>Пароль<input type="password" value={password} onChange={e=>setPassword(e.target.value)} maxLength={4096} autoComplete="current-password" required/></label>{error&&<p className="admin-login-error" role="alert">{error}</p>}<button className="admin-login-submit" disabled={busy||!login.trim()||!password}>{busy?'Входим…':'Войти'}</button></form><small>Учётную запись создаёт администратор. Системная роль определяет доступ к панели, а роль Оператора/Диспетчера назначается отдельно внутри тренировки.</small></section></main>;
}
