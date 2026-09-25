import StudentIncidentForm from './StudentIncidentForm.jsx';
import VoiceControls from './VoiceControls.jsx';
import {useEffect,useRef,useState} from 'react';

export default function StudentSession({session,fields,values,setValues,dirty,busy,act,back}){
 const [question,setQuestion]=useState(''),log=useRef(null);useEffect(()=>{if(log.current)log.current.scrollTop=log.current.scrollHeight;},[session.history]);
 fields=session.field_labels||fields;
 const full=session.format==='incident-v1';
 const active=session.status==='active',dds=session.workflow==='dds',connected=!dds||session.dds.connection==='connected';
 return <><div className="student-session-heading"><button onClick={back} disabled={busy}>← Мои тренировки</button><h1>{session.title}</h1><span>{active?'В процессе':session.result?'Проверена':'На проверке'}</span></div>
 {session.result&&<section className="student-panel student-result"><h2>Результат: {session.result.grade} / 5</h2><p>{session.result.conclusion}</p><small>Проверил: {session.result.teacher}</small><details><summary>Комментарии преподавателя</summary>{Object.entries(session.result.fields).map(([key,row])=><p key={key}><strong>{fields[key]||'Действия диспетчера'}: </strong>{row.comment}</p>)}</details></section>}
 {!active&&!session.result&&<p className="student-message">Работа передана преподавателю. Итог появится после его проверки.</p>}
 <div className={"student-work-grid "+(full?"student-full-grid":"")}><section className="student-panel"><h2>{dds?'Разговор со службой':'Разговор с заявителем'}</h2>
  {dds&&<div className="student-call-controls"><strong>{session.dds.service_name}</strong><p>{({idle:'Звонок не начат',connected:'Служба на линии',disconnected:'Связь прервана',ended:'Звонок завершён'})[session.dds.connection]}</p>{active&&<><button disabled={busy||connected} onClick={()=>act('connect')}>{session.dds.attempts?'Перезвонить':'Позвонить службе'}</button><button disabled={busy||!connected} onClick={()=>act('channel',{mode:'hangup'})}>Завершить звонок</button></>}</div>}
  <div ref={log} className="student-chat" role="log" aria-label="Разговор">{session.history.map(turn=><p key={turn.id}><strong>{({caller:'Заявитель',dispatcher:'Диспетчер',service:'Служба',system:'Система'})[turn.role]||'Собеседник'}: </strong>{turn.text}{turn.delivery==='lost'&&<small> · сообщение не доставлено</small>}</p>)}</div>
  <VoiceControls history={session.history} setQuestion={setQuestion} disabled={busy||!active||!connected}/>
  {!!session.hints.length&&<p className="student-hint">{session.hints.at(-1).text}</p>}
  {active&&<form onSubmit={async e=>{e.preventDefault();if(await act('ask',{question,source:'text'}))setQuestion('');}}><label htmlFor="student-question">{dds?'Ваша реплика службе':'Ваш вопрос заявителю'}</label><textarea id="student-question" rows={3} maxLength={2000} value={question} disabled={busy||!connected} onChange={e=>setQuestion(e.target.value)}/><div className="student-buttons"><button className="student-blue" disabled={busy||!connected||!question.trim()}>{busy?"Заявитель отвечает…":"Отправить"}</button><button type="button" disabled={busy||session.level==='hard'||session.training?.mode==='testing'} title={session.training?.mode==='testing'?'В режиме тестирования подсказки отключены':session.level==='hard'?'На сложном уровне подсказки отключены':undefined} onClick={()=>act('hint')}>Подсказка</button></div></form>}
 </section><section className="student-panel"><h2>{dds?'Полученная карточка 112':'Карточка происшествия'}</h2><p className="student-muted">{dds?'Проверьте данные и передайте сведения службе.':'Заполните карточку со слов заявителя.'}</p>
  {dds&&<details open><summary>Доступное уточнение</summary><p>{session.dds.verification_notes}</p></details>}
  {session.legacy_notice&&<p className="student-muted">{session.legacy_notice}</p>}
  {full?<StudentIncidentForm {...{session,values,setValues,busy}}/>:<fieldset disabled={busy||!active}>{Object.entries(fields).map(([key,label])=><label key={key}>{label}<textarea data-student-field={key} rows={2} maxLength={2000} value={values[key]||''} onChange={e=>setValues({...values,[key]:e.target.value})}/></label>)}</fieldset>}
  {active&&<><p className="student-muted">{dirty?'Есть несохранённые изменения':'Карточка сохранена'}</p><div className="student-buttons"><button disabled={busy} onClick={()=>act('save_card',{card:values})}>Сохранить</button><button className="student-dark" id="student-submit" disabled={busy} onClick={()=>{if(confirm('Сдать работу? После сдачи изменить карточку нельзя.'))act('submit',{card:values});}}>Сдать работу</button></div></>}
 </section></div></>;
}
