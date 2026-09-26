import {Component,useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import Shell,{sections} from './Shell.jsx';
import Teacher from './Teacher.jsx';
import Cards from './Cards.jsx';
import CardJournal from './CardJournal.jsx';
import Student from './Student.jsx';
import TrainingWorkspace from './TrainingWorkspace.jsx';
import Admin from './Admin.jsx';
import AdminLogin from './AdminLogin.jsx';
function Welcome(){const [role,setRole]=useState('teacher');const info=role==='teacher'?['Панель преподавателя','Создавайте карточки происшествий и управляйте обучением.']:role==='student'?['Панель обучающегося','Проходите тренировки и просматривайте свои результаты.']:['Панель администратора','Управляйте пользователями, контентом, результатами и состоянием системы.'];return <main className="welcome"><img className="welcome-logo" src="/hero-logo.svg" alt="112" width="185" height="106"/><div className="welcome-intro"><h1>{info[0]}</h1><p>{info[1]}</p></div><div className="welcome-roles" role="group" aria-label="Войти как"><button id="role-teacher" aria-pressed={role==='teacher'} onClick={()=>setRole('teacher')}>Преподаватель</button><button id="role-student" aria-pressed={role==='student'} onClick={()=>setRole('student')}>Обучающийся</button><button id="role-admin" aria-pressed={role==='admin'} onClick={()=>setRole('admin')}>Администратор</button></div><a className="welcome-enter" href={role==='teacher'?'/teacher':role==='student'?'/student':'/admin-login'}>Войти <span aria-hidden="true">→</span></a></main>;}
function App(){const [hash,setHash]=useState(location.hash.slice(1));useEffect(()=>{const change=()=>{setHash(location.hash.slice(1));window.scrollTo(0,0);};window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change);},[]);
 const path=location.pathname,section=path==='/cards'?'cards':(hash in sections?hash:'home');
 useEffect(()=>{document.title=path==='/student'?'Панель обучающегося · 112':path==='/admin'?'Главная администратора · 112':path==='/admin-login'?'Вход администратора · 112':path==='/'?'112 · Вход':(section==='home'?'Панель преподавателя':sections[section])+' · ИИ для проекта';document.body.dataset.framework='react';},[path,section]);
 const journal=path==='/teacher'&&(section==='home'||section==='cards');
 useEffect(()=>{document.body.classList.toggle('journal-page',path==='/teacher'||path==='/cards');return()=>document.body.classList.remove('journal-page');},[journal,section]);
 if(path==='/')return <Welcome/>;
 if(path==='/student')return <Student/>;
 if(path==='/admin-login')return <AdminLogin/>;
 if(path==='/admin')return <Admin/>;
 return <Shell section={section} journal>{journal?<CardJournal/>:path==='/cards'?<Cards/>:['create-training','monitoring','results','trainings'].includes(section)?<TrainingWorkspace key={section} section={section}/>:<Teacher section={section}/>}</Shell>;
}
class ErrorBoundary extends Component{state={error:false};static getDerivedStateFromError(){return {error:true};}render(){return this.state.error?<main style={{padding:40}}><h1>Не удалось открыть интерфейс</h1><p>Сохранённые карточки остаются в браузере.</p><button onClick={()=>location.reload()}>Обновить страницу</button></main>:this.props.children;}}
createRoot(document.getElementById('root')).render(<ErrorBoundary><App/></ErrorBoundary>);
