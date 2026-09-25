import Editor from './IncidentEditor.jsx';
import {useEffect,useState,useSyncExternalStore} from 'react';
import {createWorkshopStore} from './workshop-store.js';
import ServicesDock from './ServicesDock.jsx';
import {Cascade,Flags,ServiceDialog} from './Classification.jsx';
function Generator({store,snapshot,onStart}){
 const {state,meta,generating,reviewing}=snapshot,b=state.batch;
 const [topic,setTopic]=useState(b?.topic||''),[category,setCategory]=useState(b?.category||'1'),[count,setCount]=useState(b?.total||1);
 const [selection,setSelection]=useState(b?.classification||{}),[flags,setFlags]=useState(b?.flags||{}),[location,setLocation]=useState(b?.location||'Железногорск, Красноярский край');
 const changeGroup=k=>{setCategory(k);setSelection({});setFlags({});};

 const entries=meta.catalog.filter(x=>(category==='mixed'||x.category===category)&&Object.entries(selection).every(([k,v])=>!v||x[k]===v));
 return <section className="generator"><form id="generate-form" onSubmit={e=>{e.preventDefault();if(store.start({topic,category,total:Number(count),classification:selection,flags,location}))onStart();}}><fieldset disabled={generating||reviewing} className="creation-grid">
  <section className="creation-panel"><h2>Основные параметры</h2><div className="creation-panel-body">
   <label className="topic">Тема и пожелания<textarea id="topic" maxLength={3000} rows={5} value={topic} onChange={e=>setTopic(e.target.value)} placeholder="Например: пожар в жилом доме, разные адреса и сведения о людях"/></label>
   <label>Локация<input id="generation-location" maxLength={160} value={location} onChange={e=>setLocation(e.target.value)}/></label>
   <label className="count">Количество карточек<input id="count" type="number" min="1" max="100" required value={count} onChange={e=>setCount(e.target.value)}/></label>
   <p className="source-note">Создайте от 1 до 100 карточек вместе с эталонными ответами. Преподаватель проверяет и утверждает каждую пару отдельно.</p>
   <button id="generate" className="primary" disabled={generating||reviewing}>Сгенерировать</button>
  </div></section>
  <section className="creation-panel"><h2>Категории событий</h2><div className="creation-panel-body"><div className="category-tabs">{[['1','Пожар'],['2','ДТП'],['22','Медицина'],['14','ЖКХ'],['13','Газ'],['3','Взрыв'],['17','Человек в опасности'],['24','БПЛА']].map(([k,label])=><button type="button" key={k} data-category={k} className={category===k?'selected':''} onClick={()=>changeGroup(k)}>{label}</button>)}</div><label>Все группы происшествий<select id="category" value={category} onChange={e=>changeGroup(e.target.value)}>{Object.entries(meta.categories).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label></div>
  <h2>Параметры генерации</h2><div className="creation-panel-body"><Cascade meta={meta} category={category} selection={selection} onChange={next=>{setSelection(next);setFlags({});}}/><Flags meta={meta} value={flags} onChange={(k,v)=>setFlags({...flags,[k]:v})} allowAll={false} entries={entries}/></div></section>
 </fieldset></form>
 <p className="catalog-note">Классификатор v046/24 · {Object.keys(meta.categories).length-1} группы · {meta.catalog.length} типов происшествий. Карточки сохраняются в этом браузере.</p></section>;
}
function QueueProgress({snapshot,store}){const {state,generating,reviewing}=snapshot,b=state.batch;
 const suffix=snapshot.referencePending?'Создаётся эталонный ответ':b&&(b.done>=b.total?'Подборка готова':b.status==='error'?'Ошибка — можно повторить':b.status==='paused'?'Приостановлено':snapshot.stopRequested?'Останавливаем после текущей карточки':`Создаётся карточка ${b.done+1}`);
 return <> <div id="progress-panel" hidden={!b}>{b&&<><div className="progress-line"><span id="progress-text" role="status">Готово {b.done} из {b.total} · {suffix}</span><button id="stop" className="quiet" hidden={!generating} disabled={snapshot.stopRequested} onClick={store.stop}>Остановить после текущей</button><button id="resume" className="quiet" hidden={generating||b.done>=b.total} disabled={reviewing} onClick={store.resume}>Продолжить оставшиеся</button></div><progress id="progress" max={b.total} value={b.done}/></>}</div>
</>;}
export default function Cards(){
 const [store]=useState(createWorkshopStore),snapshot=useSyncExternalStore(store.subscribe,store.getSnapshot);
 const {state,meta,ready,reviewing,generating,referencePending}=snapshot;
 const [creating,setCreating]=useState(location.hash==='#create');
 const [filter,setFilter]=useState('all'),[search,setSearch]=useState(''),[servicesOpen,setServicesOpen]=useState(false),[editorTab,setEditorTab]=useState('card');
 useEffect(()=>{const detach=store.attach();store.init();return detach;},[store]);
 useEffect(()=>{document.body.dataset.ready=String(ready);return()=>{delete document.body.dataset.ready;};},[ready]);
 useEffect(()=>{if(ready){const id=decodeURIComponent(location.hash.slice(1));if(state.cards.some(c=>c.id===id))store.select(id);}},[ready,store]);
 const approved=state.cards.filter(c=>c.status==='approved').length;
 const list=state.cards.filter(c=>(filter==='all'||c.status===filter)&&`${c.number} ${c.content.title} ${c.content.fields.city} ${c.content.fields.street} ${c.content.fields.house} ${c.content.fields.address_text}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
 const card=state.cards.find(c=>c.id===state.selected);
 useEffect(()=>setEditorTab('card'),[card?.id]);
 const referenceMode=editorTab==='reference';
 const serviceCard=referenceMode&&card?.reference?{...card,content:card.reference.source_content}:card;
 return <main id="workshop" className="teacher-main"><a className="back-to-journal" href="/teacher">← Журнал карточек</a><section className="intro"><div><p className="eyebrow">ПОДГОТОВКА МАТЕРИАЛОВ</p><h1>От идеи до готовой карточки</h1><p>Задайте тему. Проверьте сведения. Утвердите результат.</p></div><div id="stats" className="stats">{[[state.cards.length,'Всего карточек'],[state.cards.length-approved,'На проверке'],[approved,'Утверждено']].map(([n,label])=><div className="stat" key={label}><strong>{n}</strong><span>{label}</span></div>)}</div></section>
 <div id="notice" role="status" hidden={!snapshot.notice} className={snapshot.error?'error':''}>{snapshot.notice}</div><div id="storage-warning" role="alert" hidden={!snapshot.warning}>{snapshot.warning}</div>
 {!ready?<p role="status">{snapshot.error?'Обновите страницу, чтобы повторить загрузку.':'Загружаю карточки…'}</p>:<><details id="composer" className="workshop-composer" open={creating||!card}><summary>Создание карточек · параметры GigaChat</summary><Generator store={store} snapshot={snapshot} onStart={()=>{setCreating(false);setFilter('all');setSearch('');}}/></details><QueueProgress snapshot={snapshot} store={store}/><section className="workspace"><details id="card-library" className="library" open={!card}><summary>Мои карточки · {state.cards.length}</summary><div className="library-title"><h2>Мои карточки</h2><button id="new-card" className="quiet" disabled={reviewing} onClick={()=>{store.addManual();setFilter('all');setSearch('');}}>+ Вручную</button></div><label className="sr-only" htmlFor="search">Поиск карточек</label><input id="search" type="search" placeholder="Найти по названию или адресу" value={search} onChange={e=>setSearch(e.target.value)}/><div className="filters" role="group" aria-label="Статус карточек">{[['all','Все'],['draft','Черновики'],['approved','Утверждены']].map(([key,label])=><button key={key} data-filter={key} className={filter===key?'active':''} onClick={()=>setFilter(key)}>{label}</button>)}</div>
 <div id="card-list">{list.length?list.map(c=><button key={c.id} className={'card-item '+(c.id===state.selected?'selected':'')} data-id={c.id} aria-pressed={c.id===state.selected} onClick={()=>store.select(c.id)}><span className="card-meta"><span>{c.number}</span><span className={'badge '+c.status}>{c.status==='approved'?'Утверждена':'Черновик'}</span></span><strong>{c.content.title||'Без названия'}</strong><p>{c.content.fields.address_text||[c.content.fields.city,c.content.fields.street,c.content.fields.house].filter(Boolean).join(', ')||'Адрес не заполнен'}</p></button>):<p className="empty-list">Пока нет карточек по этому фильтру.</p>}</div><button id="export-all" className="export" disabled={!state.cards.length} onClick={store.exportAll}>↓ Скачать все карточки</button><p className="storage-note">Без базы данных. Карточки сохраняются в этом браузере. Для переноса или резервной копии скачайте JSON.</p></details><Editor key={card?.id||'empty'} {...{card,meta,state,store,reviewing,generating,referencePending}} onChooseServices={()=>setServicesOpen(true)} onTabChange={setEditorTab}/></section><ServicesDock card={serviceCard} {...{meta,store,reviewing,referenceMode}} generating={snapshot.generating} warning={snapshot.warning} onChoose={()=>setServicesOpen(true)}/><ServiceDialog card={serviceCard} {...{meta,store,reviewing,referenceMode}} open={servicesOpen} onClose={()=>setServicesOpen(false)}/></>}
 </main>;
}
