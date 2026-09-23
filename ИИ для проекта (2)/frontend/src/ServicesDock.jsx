import {useEffect,useRef,useState} from 'react';
import {recommendServices,serviceOrigin} from './service-routing.js';
const quick=[['101','Служба 101'],['104','Служба 104'],['102','Служба 102'],['103','Служба 103'],['DEP_GKH','Деж. ЖКХ'],['ZEMP','ЦЭМП'],['ZODD','ЦОДД'],['MOSLIFT','Мослифт']];
export default function ServicesDock({card,meta,store,reviewing,warning,onChoose}){
 const [opened,setOpened]=useState(null),dock=useRef(null),panel=useRef(null);
 const selected=card?.content.services||[];
 const visible=[...quick.filter(([code])=>selected.includes(code)),...selected.filter(code=>!quick.some(([id])=>id===code)).map(code=>[code,meta.services[code]||code])];
 const active=opened?.cardId===card?.id&&selected.includes(opened?.code)?opened.code:null;
 const close=(restoreFocus=false)=>{setOpened(null);if(restoreFocus)dock.current?.querySelector(`[data-dock-service="${active}"]`)?.focus({preventScroll:true});};
 useEffect(()=>{
  if(!active)return;
  panel.current?.focus({preventScroll:true});
  const escape=e=>{if(e.key==='Escape'){e.preventDefault();close(true);}};
  const outside=e=>{if(!dock.current?.contains(e.target))close();};
  document.addEventListener('keydown',escape);document.addEventListener('pointerdown',outside);
  return()=>{document.removeEventListener('keydown',escape);document.removeEventListener('pointerdown',outside);};
 },[active,card?.id]);
 const choose=()=>{close();onChoose();};
 const c=card?.content,routing=active?recommendServices(meta,c):null;
 const types=active?[...meta.catalog,...(meta.legacy_catalog||[])].filter(x=>c.class_ids.includes(x.id)):[];
 return <footer ref={dock} className="services-dock" aria-label="Нижняя панель служб">
  {active&&<section ref={panel} tabIndex={-1} id="dock-service-panel" className="dock-service-panel" aria-labelledby="dock-service-title">
   <div className="dock-panel-heading"><div><small>{card.number}{c.main_service===active?' · Главная служба':''}</small><h2 id="dock-service-title">{meta.services[active]}</h2></div><button type="button" aria-label="Закрыть панель службы" onClick={()=>close(true)}>×</button></div>
   <div className="dock-panel-body"><p className="service-selection-origin">{serviceOrigin(meta,card,active)}</p><dl><dt>Происшествие</dt><dd>{types.map(x=>x.title).join('; ')||'Тип не выбран'}</dd><dt>Адрес</dt><dd>{c.fields.address_text||[c.fields.city,c.fields.street,c.fields.house].filter(Boolean).join(', ')||'Не указан'}</dd><dt>Описание</dt><dd>{c.fields.description||c.report||'Пока не заполнено'}</dd></dl>
   {routing.reasons[active]?.length>0&&<details><summary>Основание выбора по классификатору</summary><ul>{routing.reasons[active].map((reason,i)=><li key={i}>{reason}</li>)}</ul></details>}
   <div className="dock-panel-actions"><span>{card.status==='approved'?'Состав утверждён преподавателем':'Состав можно изменить по решению преподавателя'}</span><button type="button" disabled={reviewing} onClick={choose}>{card.status==='approved'?'Посмотреть состав':'Изменить состав служб'}</button></div></div>
  </section>}
  <div className="dock-context"><strong>Службы:</strong></div>
  <div className="dock-service-list" role="group" aria-label="Службы выбранной карточки">{visible.map(([code,label])=><button type="button" key={code} data-dock-service={code} className={active===code?'expanded':''} aria-expanded={active===code} aria-controls="dock-service-panel" disabled={reviewing} title={`Открыть: ${meta.services[code]||label}`} onClick={()=>setOpened(active===code?null:{cardId:card.id,code})}><span className="dock-chevron" aria-hidden="true">⌃</span>{label}</button>)}{!visible.length&&<span className="dock-empty">{card?'Службы появятся после выбора типа происшествия':'Выберите или создайте карточку'}</span>}</div>
  <button id="dock-other-services" type="button" onClick={choose} disabled={reviewing} className="dock-other" title="Другие службы — изменить состав" aria-label="Другие службы — изменить состав"><span aria-hidden="true">⌃<br/>⌄</span></button>
  <div className="dock-actions"><button id="dock-save" type="button" disabled={!card||reviewing} onClick={store.saveCurrent} title={warning?'Проверьте предупреждение о сохранении':'Сохранить текущую карточку в браузере'}>СОХРАНИТЬ</button><button id="dock-preview" type="button" disabled={!card} onClick={()=>document.getElementById('editor')?.scrollIntoView({block:'start',behavior:'auto'})}>К карточке</button></div>
 </footer>;
}
