import {useEffect,useMemo,useRef,useState} from 'react';
import {api} from './api.js';
import AddressSearch from './AddressSearch.jsx';
import {ADDRESS_KEYS,LOCATION_KEYS,addressFields} from './address-search.js';
import {Flags} from './Classification.jsx';
import {TypePicker} from './IncidentEditor.jsx';
import VoiceControls from './VoiceControls.jsx';
import {learnerServiceOrigin,recommendServices,syncLearnerServices} from './service-routing.js';
const parse=(s,fallback)=>{try{return JSON.parse(s)||fallback;}catch{return fallback;}};
const date=value=>value?new Date(value).toLocaleString('ru-RU'):'—';

function StudentDialogue({session,values,busy,act}){
 const [question,setQuestion]=useState(''),log=useRef(null),actRef=useRef(act),valuesRef=useRef(values),busyRef=useRef(busy);
 const active=session.status==='active',delay=(session.training?.coaching_delay_seconds||10)*1000;
 useEffect(()=>{actRef.current=act;},[act]);
 useEffect(()=>{valuesRef.current=values;},[values]);
 useEffect(()=>{busyRef.current=busy;},[busy]);
 useEffect(()=>{if(log.current)log.current.scrollTop=log.current.scrollHeight;},[session.history]);
 useEffect(()=>{if(!active||session.training?.mode!=='training')return;const timer=setTimeout(()=>{if(!busyRef.current)actRef.current('nudge',{card:valuesRef.current});},delay);return()=>clearTimeout(timer);},[session.id,active,session.training?.mode,session.training?.coaching_delay_seconds,session.history.length,session.training_reveals?.length,values,question,delay]);
 return <details className="incident-dialogue-fold" open>
  <summary>Разговор с заявителем <span>{Math.max(1,session.history.filter(x=>x.role==='caller').length)} реплик</span></summary>
  <section className="incident-panel caller-dialogue student-caller-dialogue">
   <h3>Разговор с заявителем</h3>
   <p className="source-note">Получайте сведения вопросами и переносите их в карточку самостоятельно.</p>
   <div ref={log} className="student-chat" role="log" aria-label="Разговор с заявителем">{session.history.map(turn=><p key={turn.id}><strong>{({caller:'Заявитель',dispatcher:'Оператор 112',system:'Система'})[turn.role]||'Собеседник'}: </strong>{turn.text}</p>)}</div>
   <VoiceControls history={session.history} setQuestion={setQuestion} disabled={busy||!active}/>
   {session.training?.mode==='training'&&!!session.training_reveals?.length&&<div className="student-coach incident-training-coach" aria-live="polite"><strong>Учебная подсказка</strong><p>Эталонное поле «{session.training_reveals.at(-1).label}»: <b>{session.training_reveals.at(-1).value}</b></p><small>Подсказка появилась после паузы в работе. Продолжайте диалог и заполнение карточки.</small></div>}
   {active&&<form onSubmit={async e=>{e.preventDefault();if(await act('ask',{question,source:'text',card:values}))setQuestion('');}}>
    <label htmlFor="student-question">Ваш вопрос заявителю</label>
    <textarea id="student-question" rows={2} maxLength={2000} value={question} disabled={busy} onChange={e=>setQuestion(e.target.value)} placeholder="Задайте уточняющий вопрос"/>
    <div className="student-buttons"><button className="student-blue" disabled={busy||!question.trim()}>{busy?'Заявитель отвечает…':'Отправить'}</button></div>
   </form>}
  </section>
 </details>;
}

function ServicePicker({meta,content,open,onClose,onApply,disabled}){
 const ref=useRef(null),[search,setSearch]=useState(''),[chosen,setChosen]=useState([]);
 useEffect(()=>{if(open){setSearch('');setChosen([...(content.services||[])]);ref.current?.showModal();}else if(ref.current?.open)ref.current.close();},[open,content.services.join('|')]);
 const choices=Object.entries(meta.services).filter(([code,label])=>(code+' '+label).toLowerCase().includes(search.toLowerCase()));
 return <dialog ref={ref} className="services-dialog student-services-dialog" aria-labelledby="student-services-title" onClose={onClose}><div className="dialog-heading"><h2 id="student-services-title">Состав служб</h2><button type="button" aria-label="Закрыть выбор служб" onClick={onClose}>×</button></div><p className="source-note">Автоматический состав сформирован по выбранному классификатору и признакам. Вы можете добавить или исключить службу вручную.</p><label>Поиск<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Название службы"/></label><div className="choices services">{choices.map(([code,label])=><label className="choice" key={code}><input type="checkbox" data-student-service={code} disabled={disabled} checked={chosen.includes(code)} onChange={e=>setChosen(previous=>e.target.checked?[...new Set([...previous,code])]:previous.filter(x=>x!==code))}/><span>{label}<small className="service-origin">{recommendServices(meta,content).services.includes(code)?'Рекомендуется классификатором':'Дополнительная служба'}</small></span></label>)}{!choices.length&&<p>Службы не найдены.</p>}</div><button type="button" className="primary" disabled={disabled} onClick={()=>{onApply(chosen);onClose();}}>Применить состав</button></dialog>;
}

export default function StudentIncidentForm({session,values,setValues,busy,act}){
 const [meta,setMeta]=useState(null),[error,setError]=useState(''),[geocoding,setGeocoding]=useState(null),[adding,setAdding]=useState(false),[servicesOpen,setServicesOpen]=useState(false);
 useEffect(()=>{let live=true;api('card_meta').then(x=>{if(live)setMeta(x);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
 const disabled=busy||session.status!=='active';
 const content={fields:Object.fromEntries(Object.keys(values).filter(k=>!k.startsWith('_')).map(k=>[k,values[k]])),report:values._report||'',class_ids:parse(values._class_ids,[]),services:parse(values._services,[]),main_service:values._main_service||'',flags:parse(values._flags,{})};
 const catalog=meta?[...meta.catalog,...(meta.legacy_catalog||[])]:[];
 const entries=useMemo(()=>content.class_ids.map(id=>catalog.find(x=>x.id===id)).filter(Boolean),[meta,values._class_ids]);
 const writeContent=(next,recalc=false)=>{
  const routed=meta&&recalc?syncLearnerServices(meta,content,{...next,services:[...(next.services||[])],flags:{...(next.flags||{})}}):next;
  setValues({...values,_class_ids:JSON.stringify(routed.class_ids||[]),_services:JSON.stringify(routed.services||[]),_main_service:routed.main_service||'',_flags:JSON.stringify(routed.flags||{})});
 };
 const change=(key,value)=>{let next={...values,[key]:value};if(LOCATION_KEYS.includes(key)&&value!==values[key]){next.latitude='';next.longitude='';setGeocoding(null);}if(['latitude','longitude'].includes(key))setGeocoding(null);setValues(next);};
 const select=(record,context)=>{setValues({...values,...Object.fromEntries(ADDRESS_KEYS.map(k=>[k,''])),...addressFields(record,context)});setGeocoding(record);};
 const clear=()=>{setValues({...values,...Object.fromEntries([...ADDRESS_KEYS,'latitude','longitude'].map(k=>[k,'']))});setGeocoding(null);};
 const field=(key,wide=false)=>{const label=session.field_labels[key]||key,auto=['phone_aon','external_number','registered_by'].includes(key),callback=key==='phone_callback'&&!session.callback_disclosed;const props={value:values[key]||'',readOnly:auto,disabled:disabled||callback,maxLength:3000,'data-student-field':session.legacy_map?.[key]||key,onChange:e=>change(key,e.target.value)};return <div key={key} data-incident-key={key} className={'incident-field '+(wide?'wide':'')}><label htmlFor={'student-'+key}>{label}</label>{wide?<textarea {...props} id={'student-'+key} rows={2}/>:<input {...props} id={'student-'+key} type={key.startsWith('phone_')?'tel':key==='control_at'?'datetime-local':'text'}/>} {key==='phone_aon'&&<p className="phone-hint">Определён автоматически · учебный номер</p>}{callback&&<p className="phone-hint">Сначала уточните номер у заявителя.</p>}</div>;};
 const store={
  replaceClass(oldId,newId){let ids=[...content.class_ids];ids=oldId?ids.map(x=>x===oldId?newId:x):[...ids,newId];ids=[...new Set(ids)];writeContent({...content,class_ids:ids},true);},
  edit(kind,key,value){if(kind==='class_ids'){const ids=value?[...new Set([...content.class_ids,key])]:content.class_ids.filter(x=>x!==key);writeContent({...content,class_ids:ids},true);}if(kind==='flag')writeContent({...content,flags:{...content.flags,[key]:value}},true);},
 };
 const setServices=codes=>{const services=[...new Set(codes.filter(code=>code in meta.services))],main=services.includes(content.main_service)?content.main_service:'';writeContent({...content,services,main_service:main},false);};
 const resetServices=()=>{const services=recommendServices(meta,content).services;const mainCandidates=[...new Set(entries.flatMap(x=>x.services||[]))].filter(code=>services.includes(code));writeContent({...content,services,main_service:mainCandidates.length===1?mainCandidates[0]:(services.length===1?services[0]:'')},false);};
 const routing=meta?recommendServices(meta,content):{services:[],reasons:{},pending:[]};
 return <div className="student-incident-form student-incident-editor incident-editor">
  <div className="incident-heading"><div><small>{session.training?.title?`${session.training.title} · карточка ${session.training.card_index||1} из ${session.training.card_total||1}`:'Учебная карточка происшествия'}</small><strong className="student-incident-title">{session.title}</strong></div><span className="badge draft">{disabled?'Просмотр':'Заполняется'}</span></div>
  <fieldset disabled={disabled} className="student-incident-fieldset">
   <div className="incident-telephony"><div className="incident-connection"><span aria-hidden="true">☎</span><strong>Телефон 112</strong><small>Учебный звонок · заявитель на линии</small></div>{['phone_aon','phone_callback','phone_scene'].map(key=>field(key))}<div className="incident-stamp"><strong>{session.id}</strong><span>Начало: {date(session.created_at)}</span><span>Оператор: {values.registered_by||'—'}</span></div></div>
   <div className="incident-registration">{['external_number','control_at','controlled_by','registered_by'].map(key=>field(key))}</div>
   <div className="incident-columns"><div className="incident-left">
    <StudentDialogue {...{session,values,busy,act}}/>
    <section className="incident-panel caller-panel">{['caller_name','caller_role'].map(key=>field(key))}</section>
    <section className="incident-panel address-panel"><h3>Адрес происшествия</h3><AddressSearch fields={values} {...{geocoding}} readonly={disabled} onSelect={select} onClear={clear}/><div className="incident-address-grid">{['country','region','city','object','district','area','street','house','block','building','apartment','entrance','floor','intercom','latitude','longitude'].map(key=>field(key))}</div>{field('address_text',true)}{field('access',true)}</section>
    <section className="incident-panel narrative-panel"><label htmlFor="student-report">Описание со слов заявителя</label><textarea id="student-report" data-student-field="_report" value={values._report||''} rows={4} maxLength={3000} onChange={e=>change('_report',e.target.value)}/>{field('vis_info',true)}{field('control_notes',true)}</section>
   </div><div className="incident-right">
    {error&&<p role="alert">{error}</p>}{meta?<><section className="incident-panel incident-flags-bar"><Flags meta={meta} value={content.flags} onChange={(key,value)=>store.edit('flag',key,value)} allowAll={false} entries={entries}/></section>
    <section className="incident-panel classification-panel"><div className="classification-heading"><h3>Тип происшествия</h3><button id="student-add-incident-type" type="button" onClick={()=>setAdding(!adding)}>{adding?'Отменить':'+ Добавить тип'}</button></div>{entries.map(entry=><TypePicker key={entry.id} {...{entry,meta,store}} readonly={disabled}/>)}{(!entries.length||adding)&&<TypePicker key="new" {...{meta,store}} readonly={disabled} onAdded={()=>setAdding(false)}/>}<div className="incident-facts">{['floors','people','injured'].map(key=>field(key))}</div>{field('description',true)}{field('extra_signs',true)}</section>
    <section className="incident-panel incident-services student-incident-services"><div className="card-section"><h3>Службы</h3><p className="source-note">После однозначного выбора классификатора службы подставляются автоматически. Состав можно изменить вручную.</p><div className="selected-services">{content.services.map(code=><span key={code} title={routing.reasons[code]?.join('\n')}>{meta.services[code]||code}<small className="service-origin">{learnerServiceOrigin(meta,content,code)}</small></span>)}{!content.services.length&&<span className="student-service-empty">Службы появятся после выбора типа происшествия</span>}</div><div className="student-buttons"><button type="button" id="student-choose-services" onClick={()=>setServicesOpen(true)}>+ Изменить состав служб</button><button type="button" id="student-reset-services" onClick={resetServices}>Вернуть автовыбор</button></div><label className="student-main-service">Главная служба<select data-student-field="_main_service" value={content.main_service} onChange={e=>writeContent({...content,main_service:e.target.value},false)}><option value="">Не выбрана</option>{content.services.map(code=><option key={code} value={code}>{meta.services[code]||code}</option>)}</select></label>{routing.pending.length>0&&<p className="source-note">Есть условия классификатора, которые требуют решения оператора: {Array.from(new Set(routing.pending.map(r=>r.condition))).filter(Boolean).join('; ')||'дополнительные условия'}.</p>}</div></section></>:<p>Загружаем классификатор…</p>}
   </div></div>
  </fieldset>
  {meta&&<ServicePicker {...{meta,content}} open={servicesOpen} onClose={()=>setServicesOpen(false)} onApply={setServices} disabled={disabled}/>} 
 </div>;
}
