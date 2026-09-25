import {useEffect,useState} from 'react';
import {api} from './api.js';
import AddressSearch from './AddressSearch.jsx';
import {ADDRESS_KEYS,LOCATION_KEYS,addressFields} from './address-search.js';
import {ClassificationEditor} from './Classification.jsx';
import {recommendServices} from './service-routing.js';
const parse=(s,fallback)=>{try{return JSON.parse(s)||fallback;}catch{return fallback;}};

export default function StudentIncidentForm({session,values,setValues,busy}){
 const [meta,setMeta]=useState(null),[error,setError]=useState(''),[geocoding,setGeocoding]=useState(null);
 useEffect(()=>{let live=true;api('card_meta').then(x=>{if(live)setMeta(x);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
 const disabled=busy||session.status!=='active';
 const content={fields:values,class_ids:parse(values._class_ids,[]),services:parse(values._services,[]),main_service:values._main_service,flags:parse(values._flags,{})};
 const change=(key,value)=>{let next={...values,[key]:value};if(LOCATION_KEYS.includes(key)&&value!==values[key]){next.latitude='';next.longitude='';setGeocoding(null);}if(['latitude','longitude'].includes(key))setGeocoding(null);setValues(next);};
 const select=record=>{setValues({...values,...Object.fromEntries(ADDRESS_KEYS.map(k=>[k,''])),...addressFields(record)});setGeocoding(record);};
 const clear=()=>{setValues({...values,...Object.fromEntries([...ADDRESS_KEYS,'latitude','longitude'].map(k=>[k,'']))});setGeocoding(null);};
 const field=key=><label key={key} className={['address_text','access','description','people','injured','extra_signs','vis_info','control_notes'].includes(key)?'student-field-wide':''}>{session.field_labels[key]}{['phone_aon','external_number','registered_by'].includes(key)?<input value={values[key]||''} readOnly data-student-field={session.legacy_map?.[key]||key}/>:<input data-student-field={session.legacy_map?.[key]||key} type={key.startsWith('phone_')?'tel':key==='control_at'?'datetime-local':'text'} value={values[key]||''} maxLength={3000} disabled={key==='phone_callback'&&!session.callback_disclosed} onChange={e=>change(key,e.target.value)}/>}</label>;
 const store={edit(kind,key,value){const next={...content};if(kind==='class_ids')next.class_ids=value?[...new Set([...next.class_ids,key])]:next.class_ids.filter(x=>x!==key);if(kind==='flag')next.flags={...next.flags,[key]:value};setValues({...values,_class_ids:JSON.stringify(next.class_ids),_flags:JSON.stringify(next.flags)});}};
 return <div className="student-incident-form">
  <fieldset disabled={disabled}>
   <section><h3>Заявитель и связь</h3><div className="student-fields-grid">{['phone_aon','phone_callback','phone_scene','caller_name','caller_role'].map(field)}</div>{!session.callback_disclosed&&<p className="student-muted">Обратный телефон можно записать после вопроса заявителю.</p>}</section>
   <section><h3>Адрес происшествия</h3><AddressSearch fields={values} {...{geocoding}} readonly={disabled} onSelect={select} onClear={clear}/><div className="student-fields-grid address-fields">{['country','region','city','object','district','area','street','house','block','building','apartment','entrance','floor','intercom','latitude','longitude','address_text','access'].map(field)}</div></section>
   <section><h3>Обстоятельства происшествия</h3><label>Описание со слов заявителя<textarea data-student-field="_report" value={values._report} rows={3} maxLength={3000} onChange={e=>change('_report',e.target.value)}/></label><div className="student-fields-grid">{['description','people','injured','floors','extra_signs','vis_info'].map(field)}</div></section>
   {error&&<p role="alert">{error}</p>}{meta?<><ClassificationEditor {...{meta,content,store}}/><section><h3>Службы реагирования</h3><p className="student-muted">Выберите состав служб по полученным сведениям.</p><button type="button" onClick={()=>setValues({...values,_services:JSON.stringify(recommendServices(meta,content).services)})}>Подобрать по моей классификации</button><div className="student-service-choices">{Object.entries(meta.services).map(([code,name])=><label key={code}><input type="checkbox" data-student-service={code} checked={content.services.includes(code)} onChange={e=>setValues({...values,_services:JSON.stringify(e.target.checked?[...content.services,code]:content.services.filter(x=>x!==code)),_main_service:!e.target.checked&&values._main_service===code?'':values._main_service})}/>{name}</label>)}</div><label>Главная служба<select data-student-field="_main_service" value={values._main_service} onChange={e=>change('_main_service',e.target.value)}><option value="">Не выбрана</option>{content.services.map(code=><option key={code} value={code}>{meta.services[code]||code}</option>)}</select></label></section></>:<p>Загружаем классификатор…</p>}
   <details><summary>Регистрация и контроль</summary><div className="student-fields-grid">{['external_number','registered_by','control_at','controlled_by','control_notes'].map(field)}</div></details>
  </fieldset>
 </div>;
}
