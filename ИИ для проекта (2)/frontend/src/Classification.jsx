import {recommendServices,serviceOrigin} from './service-routing.js';
import {useEffect,useMemo,useRef,useState} from 'react';
const unique=(rows,key)=>[...new Set(rows.map(x=>x[key]).filter(Boolean))];
export function Cascade({meta,category,selection,onChange}){
 const base=meta.catalog.filter(x=>category==='mixed'||x.category===category);
 const first=base.filter(x=>!selection.sign1||x.sign1===selection.sign1);
 const second=first.filter(x=>!selection.sign2||x.sign2===selection.sign2);
 const last=second.filter(x=>!selection.sign3||x.sign3===selection.sign3);
 const set=(key,value)=>{const order=['sign1','sign2','sign3','id'],next={...selection};for(const k of order.slice(order.indexOf(key)))delete next[k];if(value)next[key]=value;onChange(next);};
 return <div className="classification-cascade">{category==='mixed'?<p className="source-note">Выберите группу, чтобы уточнить признаки. В режиме «Разные происшествия» карточки создаются по разным группам.</p>:<>{[['sign1','Где / тип происшествия',base,true],['sign2','Объект / обстоятельства',first,!!selection.sign1],['sign3','Признак происшествия',second,!!selection.sign2]].map(([key,label,rows,enabled])=>{const values=unique(rows,key);return values.length>0&&<div className="cascade-row" key={key}><span>{label}</span><div className="cascade-choices"><button type="button" disabled={!enabled} className={!selection[key]?'selected':''} onClick={()=>set(key,'')}>Любой</button>{enabled&&values.map(v=><button type="button" key={v} className={selection[key]===v?'selected':''} onClick={()=>set(key,v)}>{v}</button>)}</div></div>;})}
 {selection.sign1&&<label className="leaf-select">Итоговый тип<select value={selection.id||''} onChange={e=>set('id',e.target.value)}><option value="">Все подходящие ({last.length})</option>{last.map(x=><option key={x.id} value={x.id}>{x.title||x.sign1} · {x.id}</option>)}</select></label>}
 <p className="classification-count">Подходящих типов: {selection.id?1:last.length}</p></>}</div>;
}
export function Flags({meta,value={},onChange,allowAll=true,entries=[]}){
 const text=entries.flatMap(x=>(x.rules||[]).map(r=>r.condition)).join(' ').toLowerCase();
 const terms={threat:/угроз|ул -/,offence:/правонаруш/,medical:/мед\./,evacuation:/эвакуац/,gas:/газифик/,not_on_scene:/не на месте/};
 const available=Object.entries(meta.flags).filter(([k])=>allowAll||['injured','no_access'].includes(k)||terms[k]?.test(text));
 const primary=['injured','no_access','threat'];
 const render=([key,label])=><label key={key}>{label}<select data-flag={key} value={value[key]||'unknown'} onChange={e=>onChange(key,e.target.value)}><option value="unknown">Неизвестно / не задано</option><option value="yes">Да</option><option value="no">Нет</option></select></label>;
 return <div className="flags-container"><div className="incident-flags">{available.filter(([k])=>primary.includes(k)).map(render)}</div>{available.some(([k])=>!primary.includes(k))&&<details><summary>Дополнительные условия</summary><div className="incident-flags">{available.filter(([k])=>!primary.includes(k)).map(render)}</div></details>}</div>;
}
export function ClassificationEditor({meta,content,store}){
 const selected=content.class_ids.map(id=>[...meta.catalog,...(meta.legacy_catalog||[])].find(x=>x.id===id)).filter(Boolean);
 const [group,setGroup]=useState(()=>selected[0]&&meta.categories[selected[0].category]?selected[0].category:'1');
 const [selection,setSelection]=useState({});
 const candidate=meta.catalog.find(x=>x.id===selection.id);
 return <section className="card-section classification-editor"><h3>Классификация происшествия</h3><div className="selected-types">{selected.map(x=><div key={x.id} className="selected-type"><strong>{x.title}</strong><span>{x.group} · {[x.sign1,x.sign2,x.sign3].filter(Boolean).join(' → ')}</span><small>{x.id.startsWith('demo-')?'Ранее созданный пример':`Код ${x.id} · строка ${x.source_row} классификатора`}</small><button type="button" aria-label={'Убрать тип '+x.title} onClick={()=>store.edit('class_ids',x.id,false)}>×</button></div>)}</div>
 <details><summary>Добавить или изменить тип происшествия</summary><label>Группа происшествий<select id="editor-category" value={group} onChange={e=>{setGroup(e.target.value);setSelection({});}}>{Object.entries(meta.categories).filter(([k])=>k!=='mixed').map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label><Cascade meta={meta} category={group} selection={selection} onChange={setSelection}/><button type="button" disabled={!candidate} onClick={()=>store.edit('class_ids',candidate.id,true)}>Добавить выбранный тип</button></details>
 <h3>Дополнительные признаки</h3><Flags meta={meta} value={content.flags} onChange={(k,v)=>store.edit('flag',k,v)} allowAll={false} entries={selected}/>
 {selected.filter(x=>x.extra_signs).map(x=><p className="source-note" key={x.id}>Дополнительно по классификатору: {x.extra_signs}</p>)}
 </section>;
}
export function Services({meta,content,card,store,onChoose}){
 const entries=useMemo(()=>content.class_ids.map(id=>meta.catalog.find(x=>x.id===id)).filter(Boolean),[meta,content.class_ids]);
 const mainCandidates=[...new Set(entries.flatMap(x=>x.services))];
 const routing=recommendServices(meta,content);
 return <section className="card-section"><h3>Службы</h3><p className="source-note">Службы выбираются автоматически по типу и признакам карточки. Преподаватель может дополнить или изменить состав; его решения сохраняются при пересчёте.</p><div className="selected-services">{content.services.map(code=><span key={code} title={routing.reasons[code]?.join("\n")}>{meta.services[code]||code}<small className="service-origin">{serviceOrigin(meta,card,code)}</small></span>)}</div><button type="button" id="choose-services" onClick={onChoose}>+ Изменить состав служб</button><button type="button" id="reset-services" onClick={store.resetServices}>Вернуть автовыбор</button>
 <label style={{marginTop:14}}>Главная служба<select id="main-service" value={content.main_service} onChange={e=>store.edit('main_service',null,e.target.value)}><option value="">Не выбрана</option>{Object.entries(meta.services).map(([code,label])=><option key={code} value={code}>{label}</option>)}</select></label>
 {mainCandidates.length>0&&<p className="source-note">Главная служба по выбранным строкам классификатора: {mainCandidates.map(k=>meta.services[k]).join('; ')}.</p>}
 <details className="routing-reference"><summary>Условия привлечения служб из классификатора</summary><p className="source-note">Базовый состав и поддерживаемые условия применены автоматически. Условия без соответствующих полей требуют решения преподавателя. Пустые ячейки не трактуются как запрет; «нет реагирования» учитывается отдельно.</p>{entries.map(x=><div key={x.id}><h4>{x.title} · {x.id}</h4><div className="routing-scroll"><table><thead><tr><th>Служба</th><th>Условие</th><th>Значение в источнике</th></tr></thead><tbody>{x.rules.map(r=><tr key={r.column}><td>{meta.services[r.service]}</td><td>{r.condition||'Отдельное условие в заголовке не указано'}</td><td>{r.value}<small> {r.column}{x.source_row}</small></td></tr>)}</tbody></table></div></div>)}</details>
 {routing.pending.length>0&&<p className="source-note">Есть условия для ручной проверки: {Array.from(new Set(routing.pending.map(r=>r.condition))).join("; ")}. Они не добавляют службы автоматически.</p>}<p className="source-note">Выбор службы не отправляет карточку и не вызывает экипаж.</p>
 </section>;
}

export function ServiceDialog({meta,card,store,open,onClose,reviewing,referenceMode=false}){
 const dialog=useRef(null),[search,setSearch]=useState(''),[chosen,setChosen]=useState([]);
 const readonly=referenceMode||!card||card.status==='approved'||reviewing;
 useEffect(()=>{if(open){setSearch('');setChosen([...(card?.content.services||[])]);dialog.current.showModal();}else dialog.current.close();},[open,card?.id]);
 const choices=Object.entries(meta.services).filter(([code,label])=>(code+' '+label).toLowerCase().includes(search.toLowerCase()));
 return <dialog id="services-picker" ref={dialog} className="services-dialog" aria-labelledby="services-picker-title" onClose={onClose}><div className="dialog-heading"><h2 id="services-picker-title">{readonly?'Справочник служб':'Состав служб'}</h2><button type="button" aria-label="Закрыть выбор служб" onClick={onClose}>×</button></div>{!card&&<p>Создайте или выберите карточку, чтобы назначить ей службы.</p>}{card?.status==='approved'&&<p>Карточка утверждена. Для изменения служб верните её на доработку.</p>}{referenceMode&&<p>Состав служб на момент создания эталона. Для изменения откройте вкладку «Карточка», затем обновите эталон.</p>}<p className="source-note">Автовыбор учитывает классификатор. Выберите изменения и нажмите «Применить состав». Закрытие окна без применения сохранит прежний состав.</p><label>Поиск<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Название службы"/></label><div className="choices services">{choices.map(([code,label])=><label className="choice" key={code}><input type="checkbox" data-service={code} disabled={readonly} checked={chosen.includes(code)} onChange={e=>setChosen(previous=>e.target.checked?[...previous,code]:previous.filter(x=>x!==code))}/><span>{label}{card&&<small className="service-origin">{serviceOrigin(meta,card,code)}</small>}</span></label>)}{!choices.length&&<p>Службы не найдены. Измените запрос.</p>}</div><button type="button" className="primary" onClick={()=>{if(!readonly)store.setServices(chosen);onClose();}}>{readonly?'Закрыть':'Применить состав'}</button></dialog>;
}
