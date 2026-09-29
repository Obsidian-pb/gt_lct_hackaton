import AddressSearch from './AddressSearch.jsx';
import {useState} from 'react';
import {Cascade,Flags,Services} from './Classification.jsx';
import ReferenceAnswer from './ReferenceAnswer.jsx';
import CallerDialogue from './CallerDialogue.jsx';
import {referenceCurrent} from './reference-state.js';
import CallerRoleSelect from './CallerRoleSelect.jsx';
const date=value=>value?new Date(value).toLocaleString('ru-RU'):'—';

export function TypePicker({entry,meta,store,readonly,onAdded}){
 const [group,setGroup]=useState(entry?.category||'1');
 const [selection,setSelection]=useState(entry?{sign1:entry.sign1,sign2:entry.sign2,sign3:entry.sign3,id:entry.id}:{});
 const candidate=meta.catalog.find(x=>x.id===selection.id);
 const change=next=>{setSelection(next);const matches=meta.catalog.filter(x=>x.category===group&&Object.entries(next).every(([key,value])=>!value||x[key]===value));if(matches.length===1){store.replaceClass(entry?.id,matches[0].id);onAdded?.();}};
 return <section className="incident-type"><div className="incident-type-title"><strong>{entry?entry.title:'Добавить тип происшествия'}</strong>{entry&&!readonly&&<button type="button" aria-label={'Убрать тип '+entry.title} onClick={()=>store.edit('class_ids',entry.id,false)}>×</button>}</div><fieldset disabled={readonly}>
  <label className="incident-group">Группа происшествий<select aria-label="Группа происшествий" value={group} onChange={e=>{setGroup(e.target.value);setSelection({});}}>{Object.entries(meta.categories).filter(([k])=>k!=='mixed').map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
  <Cascade meta={meta} category={group} selection={selection} onChange={change}/>
  {!readonly&&selection.id!==entry?.id&&<p className="source-note">Уточните признаки до одного итогового типа — он применится к карточке автоматически.</p>}
  {!readonly&&candidate&&candidate.id!==entry?.id&&<button type="button" onClick={()=>{store.replaceClass(entry?.id,candidate.id);onAdded?.();}}>Применить тип</button>}
 </fieldset></section>;
}

export default function IncidentEditor({card,meta,state,store,reviewing,generating,referencePending,reviewFeedback,reviewError,onChooseServices,onTabChange}){
 const [adding,setAdding]=useState(false);
 if(!card)return <article id="editor" className="editor incident-editor"><div className="empty"><h2>Создайте или выберите карточку</h2><p>Карточка и её эталон откроются здесь в одинаковой форме.</p></div></article>;
 const isReference=false,approved=card.status==='approved',reference=card.reference,manualReference=reference?.version!==2;
 const referenceReady=!!reference&&referenceCurrent(card),teacherReady=!!state.teacher?.trim(),canApprove=!approved&&!generating&&!reviewing&&referenceReady&&card.reference_checked===true&&teacherReady;
 const approvalBlocker=!teacherReady?'Укажите имя преподавателя.':!card.content.title.trim()?'Укажите название карточки.':!card.content.report.trim()?'Заполните сообщение заявителя.':!card.content.fields.description.trim()?'Заполните описание происшествия.':!card.content.fields.address_text.trim()&&!(card.content.fields.city.trim()&&card.content.fields.street.trim())?'Укажите адрес или явно запишите, что место пока неизвестно.':!card.content.class_ids.length||!card.content.main_service?'Выберите тип происшествия и главную службу.':!reference?'Сначала создайте эталонный ответ.':!referenceReady?'Карточка изменена после создания эталона. Обновите эталон перед утверждением.':card.reference_checked!==true?'Подтвердите проверку карточки перед утверждением.':'';
 const content=isReference&&reference?reference.source_content:card.content;
 const expected=reference?.answer.expected_fields||{};
 const locked=approved||(isReference&&(generating||!!referencePending||!reference));
 const labels=Object.fromEntries(Object.values(meta.groups).flatMap(([,fields])=>Object.entries(fields)));
 const entries=content.class_ids.map(id=>[...meta.catalog,...(meta.legacy_catalog||[])].find(x=>x.id===id)).filter(Boolean);
 const field=(key,wide=false)=>{
  const answer=isReference?expected[key]:null,value=answer?answer.value:content.fields[key]||'',unavailable=isReference&&!answer;
  const different=answer&&answer.value!==card.content.fields[key];
  const id=(isReference?'r-':'f-')+key;
  const phone=key.startsWith('phone_'),aon=key==='phone_aon';
  const needsQuestion=!isReference&&key==='phone_callback'&&card.caller_scenario&&!card.caller_dialogue?.callback_disclosed;
  const props={id,value,maxLength:3000,disabled:locked||unavailable||needsQuestion,readOnly:aon,autoComplete:phone?'off':undefined,'aria-describedby':phone?id+'-hint':undefined,onChange:e=>isReference?store.editReference('expected_fields',key,e.target.value):store.edit('field',key,e.target.value)};
  return <div key={key} data-incident-key={key} className={'incident-field '+(wide?'wide ':'')+(different?'different':'')}><label htmlFor={id}>{labels[key]}{unavailable&&<small> · данные карточки</small>}</label>{key==='caller_role'?<CallerRoleSelect {...props} data-field={!isReference?key:undefined} disabled={locked||unavailable}/>:wide?<textarea {...props} data-field={!isReference?key:undefined} data-reference-field={answer?key:undefined} rows={2}/>:<input {...props} data-field={!isReference?key:undefined} data-reference-field={answer?key:undefined} type={phone?'tel':key==='control_at'?'datetime-local':'text'}/>}
   {phone&&<p className="phone-hint" id={id+'-hint'}>{aon?(card.telephony?.mode==='simulated'&&value===card.content.fields.phone_aon?'Определён автоматически · условный номер':'Номер входящего звонка'):key==='phone_callback'?(needsQuestion?'Сначала уточните телефон в разговоре с заявителем':isReference&&reference?.source_scenario?'Известен заявителю заранее · уточняется диспетчером':'Для перезвона · может отличаться от АОН'):'Контакт человека на месте происшествия'}</p>}
   {answer&&<details className="field-evidence"><summary>{different?'Отличается от карточки · источник':'Источник'}</summary>{different&&<p>В карточке: {card.content.fields[key]||'Не заполнено'}</p>}<textarea aria-label={'Цитата: '+labels[key]} data-reference-evidence={key} rows={2} maxLength={1000} disabled={locked} value={answer.evidence} onChange={e=>store.editReference('expected_fields',key,e.target.value,'evidence')}/></details>}
  </div>;
 };
 return <article id="editor" className="editor incident-editor" inert={reviewing}>
  <div className="incident-heading"><div><small>Происшествие {card.number}</small><input id="card-title" aria-label="Название карточки" maxLength={160} value={card.content.title} readOnly={approved||isReference} onChange={e=>store.edit('content','title',e.target.value)}/></div><span className={'badge '+card.status}>{approved?'Утверждено':'Черновик'}</span></div>
  <div id="incident-form">
   <div className="incident-telephony"><div className="incident-connection"><span aria-hidden="true">☎</span><strong>Учебная карточка</strong><small>Имитация АОН · без реального звонка</small></div>{['phone_aon','phone_callback','phone_scene'].map(key=>field(key))}<div className="incident-stamp"><strong>{card.number}</strong><span>Создана: {date(card.created_at)}</span><span>Версия {card.revision}</span></div></div>
   <div className="incident-registration">{['external_number','control_at','controlled_by','registered_by'].map(key=>field(key))}</div>
   <div className="incident-columns"><div className="incident-left">
    {!isReference&&<details className="incident-dialogue-fold"><summary>Разговор с заявителем <span>{card.caller_dialogue?.turns?.length?`${card.caller_dialogue.turns.length} реплик`:'Задать вопрос'}</span></summary><CallerDialogue {...{card,store,reviewing,generating}}/></details>}
    <section className="incident-panel caller-panel">{['caller_name','caller_role'].map(key=>field(key))}</section>
    <section className="incident-panel address-panel"><h3>Адрес происшествия</h3><AddressSearch fields={content.fields} geocoding={card.geocoding} readonly={locked} onSelect={store.selectAddress} onClear={store.clearAddress}/><div className="incident-address-grid">{['country','region','city','object','district','area','street','house','block','building','apartment','entrance','floor','intercom','latitude','longitude'].map(key=>field(key))}</div>{field('address_text',true)}{field('access',true)}</section>
    <section className="incident-panel narrative-panel"><label htmlFor={isReference?'reference-report':'report'}>Описание со слов заявителя</label><textarea id={isReference?'reference-report':'report'} rows={4} maxLength={6000} value={content.report} disabled={approved||isReference} onChange={e=>store.edit('content','report',e.target.value)}/>{field('vis_info',true)}{field('control_notes',true)}</section>
   </div><div className="incident-right">
    <fieldset disabled={approved||isReference} className="incident-panel incident-flags-bar"><Flags meta={meta} value={content.flags} onChange={(key,value)=>store.edit('flag',key,value)} allowAll={false} entries={entries}/></fieldset>
    <section className="incident-panel classification-panel"><div className="classification-heading"><h3>Тип происшествия</h3>{!isReference&&!approved&&<button id="add-incident-type" type="button" onClick={()=>setAdding(!adding)}>{adding?'Отменить':'+ Добавить тип'}</button>}</div>{entries.map(entry=><TypePicker key={entry.id} {...{entry,meta,store}} readonly={approved||isReference}/>)}{(!entries.length||adding)&&!isReference&&!approved&&<TypePicker key="new" {...{meta,store}} onAdded={()=>setAdding(false)}/>}<div className="incident-facts">{['floors','people','injured'].map(key=>field(key))}</div>{field('description',true)}{field('extra_signs',true)}</section>
    {!isReference&&<fieldset disabled={approved} className="incident-panel incident-services"><Services meta={meta} content={content} {...{card,store}} onChoose={onChooseServices}/></fieldset>}
   </div></div>
  </div>
  <section className="incident-panel training-card-settings"><h3>Разговор для обучающегося</h3><p className="source-note">После утверждения карточка появится у обучающегося. Он услышит только первую реплику, остальные сведения получит вопросами к заявителю.</p><p className="source-note">Режим прохождения — «Обучение» или «Тестирование» — преподаватель выбирает при назначении сценария.</p><label>Первая реплика заявителя<textarea id="training-opening" disabled={approved||reviewing} rows={2} maxLength={2000} value={card.training_opening??card.content.report.trim().split(/(?<=[.!?…])\s+/)[0]?.slice(0,500)??''} onChange={e=>store.edit('training','training_opening',e.target.value)}/></label>{approved&&<><p>{card.training_task_id?'Доступна обучающимся · утверждённая версия':'Эта ранее утверждённая карточка ещё не добавлена в тренировки.'}</p><button type="button" disabled={reviewing} onClick={store.publishTraining}>{card.training_task_id?'Проверить доступность тренировки':'Добавить в тренировки обучающегося'}</button></>}</section>
  {manualReference&&<ReferenceAnswer {...{card,meta,store,generating,referencePending}}/>}
  <section className={'review-box '+(approved?'approved':'')}>
   <h3>{approved?'Карточка утверждена':'Проверка преподавателем'}</h3>
   {approved?<><p>{card.review.teacher} · {date(card.review.at)}</p><p>{card.review.note||'Без замечаний'}</p>{card.training_publish_error&&<p role="alert">Карточка утверждена, но не опубликована в тренировки: {card.training_publish_error}</p>}<button id="reopen" type="button" onClick={store.reopen}>Вернуть на доработку</button></>:<>
    <div className="field-grid"><label>Преподаватель<input id="teacher" maxLength={160} value={state.teacher} onChange={e=>store.edit('teacher',null,e.target.value)}/></label><label>Комментарий<input id="review-note" maxLength={3000} value={card.review_note||''} onChange={e=>store.edit('note',null,e.target.value)}/></label></div>
    {!manualReference&&<label className="reference-confirm"><input id="reference-reviewed" type="checkbox" checked={card.reference_checked===true&&referenceReady} onChange={e=>store.edit('reference_checked',null,e.target.checked)}/>Я проверил карточку. Её заполненные поля станут эталоном для обучающегося.</label>}
    <p className="source-note">Готовность: преподаватель — {teacherReady?'да':'нет'}; эталон — {referenceReady?'да':'нет'}; проверка — {card.reference_checked===true?'да':'нет'}.</p>
    <p id="approval-requirement" className="review-requirement" hidden={!approvalBlocker}>{approvalBlocker}</p>
    <div className="review-actions"><button id="validate" type="button" disabled={generating||reviewing} onClick={()=>store.review('validate')}>Проверить поля</button><button id="approve" type="button" className="primary" disabled={generating||reviewing} aria-describedby="approval-requirement approval-feedback" onClick={()=>canApprove?store.review('approve'):store.notify(approvalBlocker,true,true)}>{reviewing?'Проверяем…':'Утвердить карточку'}</button></div>
   </>}
   {reviewFeedback&&<p id="approval-feedback" className={'review-feedback '+(reviewError?'error':'')} role={reviewError?'alert':'status'}>{reviewFeedback}</p>}
   <button id="export-one" type="button" onClick={store.exportOne}>Скачать карточку</button>
  </section>
  <details className="incident-history"><summary>История карточки · {card.history.length}</summary>{card.history.slice().reverse().map((h,i)=><p key={i}>{date(h.at)} · {h.text}</p>)}</details>
 </article>;
}
