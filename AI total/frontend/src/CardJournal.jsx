import {Fragment,useEffect,useMemo,useState,useSyncExternalStore} from 'react';
import {createWorkshopStore} from './workshop-store.js';
import {Icon} from './Shell.jsx';
import {referenceCurrent} from './reference-state.js';
const statuses={draft:'Черновик',approved:'Утверждена'};
const address=c=>c.fields.address_text||[c.fields.city,c.fields.street,c.fields.house].filter(Boolean).join(', ')||'—';
const cardURL=id=>'/cards#'+encodeURIComponent(id);
const localDate=value=>{const d=new Date(value);return Number.isNaN(d.getTime())?'':`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};

export default function CardJournal(){
 const [store]=useState(createWorkshopStore),snapshot=useSyncExternalStore(store.subscribe,store.getSnapshot);
 const [query,setQuery]=useState(''),[filtersOpen,setFiltersOpen]=useState(true),[date,setDate]=useState(''),[type,setType]=useState(''),[status,setStatus]=useState(''),[district,setDistrict]=useState('');
 const [page,setPage]=useState(1),[pageSize,setPageSize]=useState(10),[ascending,setAscending]=useState(false),[expanded,setExpanded]=useState(new Set());
 useEffect(()=>{const detach=store.attach();store.init();return detach;},[store]);
 useEffect(()=>{document.body.dataset.journalReady=String(snapshot.ready);return()=>{delete document.body.dataset.journalReady;};},[snapshot.ready]);
 const cards=snapshot.state.cards,meta=snapshot.meta;
 const classes=useMemo(()=>new Map([...(meta?.catalog||[]),...(meta?.legacy_catalog||[])].map(c=>[c.id,c])),[meta]);
 const cardType=c=>c.content.class_ids.map(id=>classes.get(id)?.title||id).join('; ')||c.content.title||'Не указан';
 const groups=useMemo(()=>[...new Set(cards.flatMap(c=>c.content.class_ids.map(id=>classes.get(id)?.category).filter(Boolean)))].sort((a,b)=>a.localeCompare(b,'ru',{numeric:true})),[cards,classes]);
 const districts=[...new Set(cards.map(c=>c.content.fields.district?.trim()).filter(x=>x&&!/^(неизвестно|не указан|не относится)$/i.test(x)))].sort((a,b)=>a.localeCompare(b,'ru'));
 const filtered=cards.filter(c=>{
  const text=[c.number,c.content.title,c.content.report,c.content.fields.description,address(c.content),cardType(c)].join(' ').toLocaleLowerCase('ru');
  return (!query.trim()||text.includes(query.trim().toLocaleLowerCase('ru')))&&(!status||c.status===status)&&(!date||localDate(c.created_at)===date)&&(!district||c.content.fields.district?.trim()===district)&&(!type||c.content.class_ids.some(id=>classes.get(id)?.category===type));
 }).sort((a,b)=>(ascending?1:-1)*(new Date(a.created_at)-new Date(b.created_at))||a.number.localeCompare(b.number));
 const pages=Math.max(1,Math.ceil(filtered.length/pageSize)),currentPage=Math.min(page,pages),rows=filtered.slice((currentPage-1)*pageSize,currentPage*pageSize);
 const reset=()=>{setQuery('');setDate('');setType('');setStatus('');setDistrict('');setPage(1);};
 const filterChange=setter=>e=>{setter(e.target.value);setPage(1);};
 const toggle=id=>setExpanded(previous=>{const next=new Set(previous);next.has(id)?next.delete(id):next.add(id);return next;});
 return <main id="teacher-content" className="journal-main">
  <header className="journal-title"><div><h1>Карточки происшествий</h1><p>Журнал карточек и эталонных ответов преподавателя</p></div><a id="journal-new" className="journal-primary" href="/cards#create"><span aria-hidden="true">＋</span> НОВАЯ КАРТОЧКА</a></header>
  {snapshot.warning&&<p className="journal-warning" role="alert">{snapshot.warning}</p>}
  {snapshot.error&&<p className="journal-warning" role="alert">{snapshot.notice} <button onClick={()=>store.init()}>Повторить загрузку</button></p>}
  <section className="journal-search" aria-label="Поиск карточек"><Icon name="search"/><label className="journal-sr" htmlFor="journal-query">Поиск по номеру, типу происшествия, адресу или описанию</label><input id="journal-query" type="search" value={query} onChange={filterChange(setQuery)} placeholder="Поиск по номеру, типу происшествия, адресу или описанию"/><button id="journal-filter-toggle" aria-expanded={filtersOpen} aria-controls="journal-filters" onClick={()=>setFiltersOpen(!filtersOpen)}><Icon name="filter"/>Фильтры</button><button id="journal-reset" className="journal-reset" onClick={reset}>Сбросить</button></section>
  <section id="journal-filters" className="journal-filters" hidden={!filtersOpen} aria-label="Фильтры карточек">
   <label>Дата<input id="journal-date" type="date" value={date} onChange={filterChange(setDate)}/></label>
   <label>Тип происшествия<select id="journal-type" value={type} onChange={filterChange(setType)}><option value="">Все типы</option>{groups.map(g=><option key={g} value={g}>{meta?.categories[g]||g}</option>)}</select></label>
   <label>Статус<select id="journal-status" value={status} onChange={filterChange(setStatus)}><option value="">Все статусы</option>{Object.entries(statuses).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
   <label>Округ происшествия<select id="journal-district" value={district} onChange={filterChange(setDistrict)}><option value="">Все округа</option>{districts.map(d=><option key={d}>{d}</option>)}</select></label>
   <label>Обучающийся<select disabled aria-label="Обучающийся"><option>Назначение не подключено</option></select></label>
  </section>
  <section className="journal-results" aria-label="Список происшествий"><div className="journal-list-title"><h2>СПИСОК ПРОИСШЕСТВИЙ</h2><span id="journal-count" role="status">Найдено записей: {filtered.length}</span></div>
   <div className="journal-table-scroll"><table className="journal-table"><thead><tr><th className="journal-expand-col"><span className="journal-sr">Подробнее</span></th>{['Связи','ЧС','Опер.','АРМ','Номер'].map(t=><th key={t}>{t}</th>)}<th aria-sort={ascending?'ascending':'descending'}><button id="journal-sort" onClick={()=>{setAscending(!ascending);setPage(1);}}>Дата <span aria-hidden="true">{ascending?'↑':'↓'}</span></button></th>{['Время','Тип происшествия','Адрес происшествия','Статус'].map(t=><th key={t}>{t}</th>)}</tr></thead><tbody>
    {!snapshot.ready?<tr><td colSpan={11} className="journal-empty">{snapshot.error?'Не удалось загрузить карточки.':'Загружаю карточки…'}</td></tr>:!rows.length?<tr><td colSpan={11} className="journal-empty"><strong>{cards.length?'Ничего не найдено':'Пока нет карточек'}</strong><p>{cards.length?'Измените запрос или сбросьте фильтры.':'Создайте первую карточку — она появится здесь вместе с эталоном.'}</p>{cards.length?<button onClick={reset}>Сбросить фильтры</button>:<a href="/cards#create">Создать карточку →</a>}</td></tr>:rows.map(c=><Fragment key={c.id}>
     <tr className={'journal-row '+(expanded.has(c.id)?'selected':'')} data-card-row={c.id}><td><button className="journal-expand" aria-label={'Подробнее: '+c.number} aria-expanded={expanded.has(c.id)} aria-controls={'detail-'+c.id} onClick={()=>toggle(c.id)}>{expanded.has(c.id)?'⌄':'›'}</button></td>{['Связи','ЧС','Оператор','АРМ'].map(label=><td key={label} className="journal-unavailable" title={label+': сведения пока не ведутся'}>—</td>)}<td><a href={cardURL(c.id)} className="journal-number">{c.number}</a></td><td>{new Date(c.created_at).toLocaleDateString('ru-RU')}</td><td>{new Date(c.created_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</td><td><a className="journal-event" href={cardURL(c.id)}>{cardType(c)}</a></td><td className="journal-address">{address(c.content)}</td><td><span className={'journal-status '+c.status}>{statuses[c.status]}</span></td></tr>
     <tr className={'journal-description '+(expanded.has(c.id)?'selected':'')}><td/><td colSpan={10}>Описание: {c.content.fields.description||c.content.report||'Не заполнено'}</td></tr>
     {expanded.has(c.id)&&<tr className="journal-detail" id={'detail-'+c.id}><td colSpan={11}><div><span><strong>{c.content.title}</strong><br/>{c.reference?(c.status==='approved'?'Карточка и эталон утверждены':referenceCurrent(c)?'Эталон подготовлен для проверки':'Эталон требует обновления'):'Эталон ещё не создан'} · версия {c.revision}</span><a href={cardURL(c.id)}>Открыть карточку и эталон <Icon name="arrow"/></a></div></td></tr>}
    </Fragment>)}
   </tbody></table></div>
  </section>
  <footer className="journal-pagination"><span>Показано {filtered.length?(currentPage-1)*pageSize+1:0}–{Math.min(currentPage*pageSize,filtered.length)} из {filtered.length}</span><div><label>Записей на странице: <select id="journal-page-size" value={pageSize} onChange={e=>{setPageSize(Number(e.target.value));setPage(1);}}>{[10,25,50].map(n=><option key={n}>{n}</option>)}</select></label><nav aria-label="Страницы журнала"><button aria-label="Предыдущая страница" disabled={currentPage===1} onClick={()=>setPage(currentPage-1)}>‹</button>{Array.from({length:pages},(_,i)=>i+1).filter(n=>n===1||n===pages||Math.abs(n-currentPage)<2).map((n,i,all)=><Fragment key={n}>{i>0&&n-all[i-1]>1&&<span>…</span>}<button aria-label={'Страница '+n} aria-current={n===currentPage?'page':undefined} onClick={()=>setPage(n)}>{n}</button></Fragment>)}<button aria-label="Следующая страница" disabled={currentPage===pages} onClick={()=>setPage(currentPage+1)}>›</button></nav></div></footer>
  <p className="journal-footnote">Карточки сохраняются в этом браузере. Откройте запись, чтобы продолжить разговор с заявителем, проверить сведения и утвердить эталон.</p>
 </main>;
}
