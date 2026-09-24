import {Component,useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import Shell,{sections} from './Shell.jsx';
import Teacher from './Teacher.jsx';
import Cards from './Cards.jsx';
import CardJournal from './CardJournal.jsx';
function Welcome(){return <main className="welcome"><img className="welcome-logo" src="/hero-logo.svg" alt="112" width="185" height="106"/><div className="welcome-intro"><h1>Панель преподавателя</h1><p>Создавайте карточки происшествий<br/>и управляйте обучением.</p></div><a className="welcome-enter" href="/teacher">Войти <span aria-hidden="true">→</span></a></main>;}
function App(){const [hash,setHash]=useState(location.hash.slice(1));useEffect(()=>{const change=()=>{setHash(location.hash.slice(1));window.scrollTo(0,0);};window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change);},[]);
 const path=location.pathname,section=path==='/cards'?'cards':(hash in sections?hash:'home');
 useEffect(()=>{document.title=path==='/'?'112 · Вход':(section==='home'?'Панель преподавателя':sections[section])+' · ИИ для проекта';document.body.dataset.framework='react';},[path,section]);
 const journal=path==='/teacher'&&(section==='home'||section==='cards');
 useEffect(()=>{document.body.classList.toggle('journal-page',journal);return()=>document.body.classList.remove('journal-page');},[journal]);
 if(path==='/')return <Welcome/>;
 return <Shell section={section} journal={journal}>{journal?<CardJournal/>:path==='/cards'?<Cards/>:<Teacher section={section}/>}</Shell>;
}
class ErrorBoundary extends Component{state={error:false};static getDerivedStateFromError(){return {error:true};}render(){return this.state.error?<main style={{padding:40}}><h1>Не удалось открыть интерфейс</h1><p>Сохранённые карточки остаются в браузере.</p><button onClick={()=>location.reload()}>Обновить страницу</button></main>:this.props.children;}}
createRoot(document.getElementById('root')).render(<ErrorBoundary><App/></ErrorBoundary>);
