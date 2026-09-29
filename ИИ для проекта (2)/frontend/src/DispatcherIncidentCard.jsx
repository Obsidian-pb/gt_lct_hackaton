import {useEffect,useState} from 'react';
import {api} from './api.js';
import AddressSearch from './AddressSearch.jsx';
import {ADDRESS_KEYS,addressFields} from './address-search.js';
import CallbackPhone from './CallbackPhone.jsx';
import {TypePicker} from './IncidentEditor.jsx';
import {Flags} from './Classification.jsx';
import CallerRoleSelect from './CallerRoleSelect.jsx';

const protectedFields=new Set(['phone_aon','external_number','registered_by','_services','_main_service']);
const parse=(value,fallback)=>{try{return JSON.parse(value)||fallback;}catch{return fallback;}};

export default function DispatcherIncidentCard({desk,card,student,services,busy,act}){
 const [updates,setUpdates]=useState({}),[chosen,setChosen]=useState([]),[main,setMain]=useState(''),[search,setSearch]=useState(''),[meta,setMeta]=useState(null),[menu,setMenu]=useState(false),[adding,setAdding]=useState(false);
 useEffect(()=>{api('card_meta').then(setMeta).catch(()=>{});},[]);
 const values={...card.card,...updates},phone=values.phone_callback||values.phone_aon;
 const field=(key,wide=false)=>{const locked=protectedFields.has(key),value=values[key]||'';return <div className={'incident-field '+(wide?'wide':'')} key={key} data-incident-key={key}><label htmlFor={'dds-'+card.id+'-'+key}>{card.field_labels?.[key]||key}</label>{key==='caller_role'?<CallerRoleSelect id={'dds-'+card.id+'-'+key} value={value} disabled={locked} onChange={e=>setUpdates(old=>({...old,[key]:e.target.value}))}/>:wide?<textarea id={'dds-'+card.id+'-'+key} value={value} rows={2} readOnly={locked} onChange={e=>setUpdates(old=>({...old,[key]:e.target.value}))}/>:<input id={'dds-'+card.id+'-'+key} type={key.startsWith('phone_')?'tel':'text'} value={value} readOnly={locked} onChange={e=>setUpdates(old=>({...old,[key]:e.target.value}))}/>}</div>;};
 const selectAddress=(record,context)=>setUpdates(old=>({...old,...Object.fromEntries(ADDRESS_KEYS.map(key=>[key,''])),...addressFields(record,context)}));
 const clearAddress=()=>setUpdates(old=>({...old,...Object.fromEntries([...ADDRESS_KEYS,'latitude','longitude'].map(key=>[key,'']))}));
 const ids=parse(values._class_ids,[]),catalog=[...(meta?.catalog||[]),...(meta?.legacy_catalog||[])];
 const entries=ids.map(id=>catalog.find(x=>x.id===id)).filter(Boolean);
 const setClasses=next=>setUpdates(old=>({...old,_class_ids:JSON.stringify(next)}));
 const store={replaceClass(oldId,newId){setClasses([...new Set(oldId?ids.map(id=>id===oldId?newId:id):[...ids,newId])]);},edit(kind,key,value){if(kind==='class_ids')setClasses(value?[...new Set([...ids,key])]:ids.filter(id=>id!==key));if(kind==='flag')setUpdates(old=>({...old,_flags:JSON.stringify({...parse(values._flags,{}),[key]:value})}));}};
 const available=Object.entries(services).filter(([code,label])=>(code+' '+label).toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')));
 const route=()=>act(()=>api('training_route',{resource_id:desk.id,card_id:card.id,student,services:chosen,main_service:main||chosen[0],updates}));
 return <article className="dispatcher-card dispatcher-dds-review dispatcher-incident-review student-incident-form student-incident-editor incident-editor">
  <div className="incident-heading"><div><small>НА ПРОВЕРКУ ОТ ОПЕРАТОРА · {card.student}</small><strong className="student-incident-title">{card.ai_title||'Карточка '+card.id.slice(-6)}</strong></div><span className="badge draft">Проверяет диспетчер 112</span></div>
  <div className="incident-telephony"><div className="incident-connection"><span>☎</span><strong>Телефон 112</strong><small>Карточка поступила от оператора</small></div>{['phone_aon','phone_callback','phone_scene'].map(key=>field(key))}<div className="incident-stamp"><strong>{card.id}</strong><span>Оператор: {card.student}</span><span>На проверке с {new Date(card.submitted_at).toLocaleString('ru-RU')}</span></div></div>
  <div className="incident-registration">{['external_number','control_at','controlled_by','registered_by'].map(key=>field(key))}</div>
  <div className="incident-columns"><div className="incident-left">
   <section className="incident-panel caller-panel">{['caller_name','caller_role'].map(key=>field(key))}</section>
   <section className="incident-panel address-panel"><h3>Адрес происшествия</h3><AddressSearch fields={values} readonly={false} onSelect={selectAddress} onClear={clearAddress}/><div className="incident-address-grid">{['country','region','city','object','district','area','street','house','block','building','apartment','entrance','floor','intercom','latitude','longitude'].map(key=>field(key))}</div>{field('address_text',true)}{field('access',true)}</section>
   <section className="incident-panel narrative-panel"><label htmlFor={'dds-report-'+card.id}>Описание со слов заявителя</label><textarea id={'dds-report-'+card.id} value={values._report||''} rows={4} maxLength={3000} onChange={e=>setUpdates(old=>({...old,_report:e.target.value}))}/>{field('vis_info',true)}{field('control_notes',true)}</section>
  </div><div className="incident-right">
   <section className="incident-panel classification-panel"><div className="classification-heading"><h3>Тип происшествия</h3><button type="button" onClick={()=>setAdding(!adding)}>{adding?'Отменить':'+ Добавить тип'}</button></div>{meta?<>{entries.map(entry=><TypePicker key={entry.id} {...{entry,meta,store}} readonly={false}/>)}{(!entries.length||adding)&&<TypePicker key="new" {...{meta,store}} readonly={false} onAdded={()=>setAdding(false)}/>}<Flags meta={meta} value={parse(values._flags,{})} onChange={(key,value)=>store.edit('flag',key,value)} allowAll={false} entries={entries}/></>:<p>Загружаем классификатор…</p>}<div className="incident-facts">{['floors','people','injured'].map(key=>field(key))}</div>{field('description',true)}{field('extra_signs',true)}<p className="source-note">Сведения оператора можно уточнить по телефону. Службы назначаются диспетчером 112 внизу карточки.</p></section>
   <section className="incident-panel dispatcher-review-summary"><h3>Проверка карточки</h3><p><b>Телефон:</b> {phone||'не указан'}</p><p><b>Сообщение:</b> {values._report||'описание не заполнено'}</p><p><b>Адрес:</b> {values.address_text||[values.city,values.street,values.house].filter(Boolean).join(', ')||'не указан'}</p></section>
  </div></div>
  <div className="dds-dispatch-bar"><div className="dds-dispatch-label"><small>РЕШЕНИЕ ДИСПЕТЧЕРА 112</small><strong>{chosen.length?chosen.map(code=>code+' · '+services[code]).join('; '):'Службы не выбраны'}</strong></div><div className="dds-service-picker"><button type="button" aria-expanded={menu} onClick={()=>setMenu(!menu)}>Службы · {chosen.length} ▾</button>{menu&&<div className="dds-service-popup"><header><strong>Выбрать службы</strong><button type="button" onClick={()=>setMenu(false)} aria-label="Закрыть список служб">×</button></header><input aria-label="Поиск службы" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Найти службу…"/><div className="dds-service-options">{available.map(([code,label])=><label key={code}><input type="checkbox" checked={chosen.includes(code)} onChange={e=>{setChosen(old=>e.target.checked?[...old,code]:old.filter(x=>x!==code));if(!e.target.checked&&main===code)setMain('');}}/><b>{code}</b><span>{label}</span></label>)}{!available.length&&<p>Служба не найдена.</p>}</div><label className="dds-main-service">Главная служба<select value={main} onChange={e=>setMain(e.target.value)}><option value="">Первая выбранная</option>{chosen.map(code=><option key={code} value={code}>{code} · {services[code]}</option>)}</select></label></div>}</div><button type="button" className="dispatcher-primary" disabled={busy||!chosen.length} onClick={route}>Проверить и направить →</button></div>
  <CallbackPhone {...{desk,card,student,busy,act}}/>
 </article>;
}
