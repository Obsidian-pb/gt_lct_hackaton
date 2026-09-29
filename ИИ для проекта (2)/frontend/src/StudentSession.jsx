import StudentIncidentForm,{StudentDialogue} from './StudentIncidentForm.jsx';
import VoiceControls from './VoiceControls.jsx';
import {useEffect,useRef,useState} from 'react';

function TrainingReveal({session}){
 const rows=session.training_reveals||[];
 if(session.training?.mode!=='training'||!rows.length)return null;
 const last=rows.at(-1);
 return <section className="student-panel student-coach" aria-live="polite"><h2>Учебная подсказка</h2><p className="student-muted">После паузы система раскрыла одно поле эталонной карточки, чтобы помочь продолжить работу.</p><p><strong>{last.label}:</strong> {last.value}</p>{rows.length>1&&<details><summary>Ранее раскрытые поля · {rows.length-1}</summary><ol>{rows.slice(0,-1).map(row=><li key={row.number+'-'+row.field}><strong>{row.label}:</strong> {row.value}</li>)}</ol></details>}</section>;
}

function SaveActions({active,dirty,busy,values,act,handoff}){
 if(!active)return null;
 return <section className="student-card-actions"><p className="student-muted">{dirty?'Есть несохранённые изменения':'Карточка сохранена'}</p><div className="student-buttons"><button disabled={busy} onClick={()=>act('save_card',{card:values})}>Сохранить</button><button className="student-dark" id="student-submit" disabled={busy} onClick={()=>{if(confirm(handoff?'Передать карточку диспетчеру 112? После передачи изменить её нельзя.':'Сдать работу? После сдачи изменить карточку нельзя.'))act('submit',{card:values});}}>{handoff?'Передать диспетчеру 112':'Сдать работу'}</button></div></section>;
}

export default function StudentSession({session,fields,values,setValues,dirty,busy,act,back}){
 const [question,setQuestion]=useState(''),[clock,setClock]=useState(Date.now()),log=useRef(null),actRef=useRef(act),valuesRef=useRef(values),busyRef=useRef(busy);
 useEffect(()=>{const id=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(id);},[]);
 useEffect(()=>{actRef.current=act;},[act]);
 useEffect(()=>{valuesRef.current=values;},[values]);
 useEffect(()=>{busyRef.current=busy;},[busy]);
 useEffect(()=>{if(log.current)log.current.scrollTop=log.current.scrollHeight;},[session.history]);
 fields=session.field_labels||fields;
 const full=session.format==='incident-v1';
 const active=session.status==='active',dds=session.workflow==='dds',connected=!dds||session.dds.connection==='connected';
 const needsIntroduction=active&&full&&!dds&&session.call_intro==='greeting'&&!session.history.some((turn,index)=>index>0&&turn.role==='caller');
 const delay=(session.training?.coaching_delay_seconds||10)*1000;
 useEffect(()=>{
  if(!active||session.training?.mode!=='training'||(full&&!dds))return;
  const timer=setTimeout(()=>{if(!busyRef.current)actRef.current('nudge',{card:valuesRef.current});},delay);
  return()=>clearTimeout(timer);
 },[session.id,active,session.training?.mode,session.training?.coaching_delay_seconds,session.history.length,session.training_reveals?.length,values,question,full,dds,delay]);
<<<<<<< HEAD
 return <><div className="student-session-heading"><button onClick={back} disabled={busy}>← Мои тренировки</button><h1>{needsIntroduction?'Вызов 112':session.title}</h1><span>{session.status==='awaiting_call'?'Входящий вызов':active?'В процессе':session.result?'Проверена':'На проверке'}</span></div>
=======
 return <><div className="student-session-heading"><button onClick={back} disabled={busy}>← Мои тренировки</button><h1>{session.title}</h1><span>{session.status==='awaiting_call'?'Входящий вызов':active?'В процессе':session.result?'Проверена':'На проверке'}</span></div>
 {session.status==='awaiting_call'&&<section className="student-panel" role="status"><h2>Входящий учебный вызов</h2><p>Номер по АОН: {session.card.phone_aon||'Не определён'}</p><button className="student-dark" disabled={busy} onClick={()=>act('accept')}>Принять вызов и начать карточку</button></section>}
>>>>>>> ec5491b6745f1dd11607901b6ecc81befa475fae
 {active&&session.training?.seconds>0&&session.activated_at&&<p role="timer" className="student-message">До конца карточки: {Math.max(0,Math.ceil(session.training.seconds-(clock-new Date(session.activated_at).getTime())/1000))} с</p>}
 {!full&&<TrainingReveal session={session}/>} 
 {session.result&&<section className="student-panel student-result"><h2>Результат: {session.result.grade} / 5</h2><p>{session.result.conclusion}</p><small>Проверил: {session.result.teacher}</small><details><summary>Комментарии преподавателя</summary>{Object.entries(session.result.fields).map(([key,row])=><p key={key}><strong>{fields[key]||'Действия диспетчера'}: </strong>{row.comment}</p>)}</details></section>}
 {!active&&!session.result&&<p className="student-message">Работа передана преподавателю. Итог появится после его проверки.</p>}
 {needsIntroduction?<div className="student-dialogue-stage"><p className="student-message">Заявитель пока не назвал происшествие. Ответьте ему и уточните, что произошло. После его ответа откроется карточка.</p><section className="student-incident-form student-incident-editor"><StudentDialogue {...{session,values,busy,act}}/></section></div>:full&&!dds?<div className="student-card-workspace">{session.legacy_notice&&<p className="student-muted">{session.legacy_notice}</p>}<StudentIncidentForm {...{session,values,setValues,busy,act}}/><SaveActions handoff={!!session.training?.handoff_to_dds} {...{active,dirty,busy,values,act}}/></div>:<div className="student-work-grid"><section className="student-panel"><h2>{dds?'Разговор со службой':'Разговор с заявителем'}</h2>
  {dds&&<div className="student-call-controls"><strong>{session.dds.service_name}</strong><p>{({idle:'Звонок не начат',connected:'Служба на линии',disconnected:'Связь прервана',ended:'Звонок завершён'})[session.dds.connection]}</p>{active&&<><button disabled={busy||connected} onClick={()=>act('connect')}>{session.dds.attempts?'Перезвонить':'Позвонить службе'}</button><button disabled={busy||!connected} onClick={()=>act('channel',{mode:'hangup'})}>Завершить звонок</button></>}</div>}
  <div ref={log} className="student-chat" role="log" aria-label="Разговор">{session.history.map(turn=><p key={turn.id}><strong>{({caller:'Заявитель',dispatcher:'Диспетчер',service:'Служба',system:'Система'})[turn.role]||'Собеседник'}: </strong>{turn.text}{turn.delivery==='lost'&&<small> · сообщение не доставлено</small>}</p>)}</div>
  <VoiceControls history={session.history} setQuestion={setQuestion} disabled={busy||!active||!connected}/>
  {active&&<form onSubmit={async e=>{e.preventDefault();if(await act('ask',{question,source:'text'}))setQuestion('');}}><label htmlFor="student-question">{dds?'Ваша реплика службе':'Ваш вопрос заявителю'}</label><textarea id="student-question" rows={3} maxLength={2000} value={question} disabled={busy||!connected} onChange={e=>setQuestion(e.target.value)}/><div className="student-buttons"><button className="student-blue" disabled={busy||!connected||!question.trim()}>{busy?'Собеседник отвечает…':'Отправить'}</button></div></form>}
 </section><section className="student-panel"><h2>{dds?'Полученная карточка 112':'Карточка происшествия'}</h2><p className="student-muted">{dds?'Проверьте данные и передайте сведения службе.':'Заполните карточку со слов заявителя.'}</p>
  {dds&&<details open><summary>Доступное уточнение</summary><p>{session.dds.verification_notes}</p></details>}
  {session.legacy_notice&&<p className="student-muted">{session.legacy_notice}</p>}
  {full?<StudentIncidentForm {...{session,values,setValues,busy,act}}/>:<fieldset disabled={busy||!active}>{Object.entries(fields).map(([key,label])=><label key={key}>{label}<textarea data-student-field={key} rows={2} maxLength={2000} value={values[key]||''} onChange={e=>setValues({...values,[key]:e.target.value})}/></label>)}</fieldset>}
  <SaveActions handoff={!!session.training?.handoff_to_dds} {...{active,dirty,busy,values,act}}/>
 </section></div>}
 </>;
}
