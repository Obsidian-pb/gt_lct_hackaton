import {useState} from 'react';

export default function CallerDialogue({card,store,reviewing,generating}){
 const [question,setQuestion]=useState('');
 const dialogue=card.caller_dialogue,prepared=!!card.caller_scenario;
 return <section className="incident-panel caller-dialogue">
  <h3>Разговор с заявителем</h3>
  <p className="source-note">Пробный разговор для преподавателя. Задавайте вопросы от лица диспетчера; полученные сведения вносите в карточку вручную.</p>
  {!prepared?<><p>Для этой карточки разговор ещё не подготовлен.</p><button id="prepare-caller" disabled={card.status==='approved'||reviewing||generating} onClick={store.prepareCaller}>Подготовить разговор</button>{card.status==='approved'&&<p>Верните карточку на доработку, чтобы добавить разговор.</p>}</>:<>
   <div className="caller-transcript" role="log" aria-label="История разговора" aria-live="polite">
    <p><strong>Заявитель: </strong>{card.content.report||'Что вы хотите уточнить?'}</p>
    {(dialogue?.turns||[]).map((turn,i)=><p key={i}><strong>{turn.role==='caller'?'Заявитель':'Диспетчер'}: </strong>{turn.text}</p>)}
   </div>
   <form onSubmit={async e=>{e.preventDefault();if(await store.askCaller(question))setQuestion('');}}>
    <label htmlFor="caller-question">Ваш вопрос заявителю</label>
    <textarea id="caller-question" rows={2} maxLength={2000} value={question} onChange={e=>setQuestion(e.target.value)} disabled={reviewing||generating} placeholder="Например: на какой номер вам перезвонить?"/>
    <button id="ask-caller" disabled={!question.trim()||reviewing||generating}>{reviewing?'Заявитель отвечает…':'Спросить заявителя'}</button>
    <button type="button" id="reset-caller" disabled={reviewing||generating||!dialogue?.turns?.length} onClick={store.resetCaller}>Начать разговор заново</button>
   </form>
   <p className="phone-hint">{dialogue?.callback_disclosed?'Заявитель назвал телефон — можно записать его в поле «Обратный телефон».':'Обратный телефон станет доступен для ввода после уточнения у заявителя.'}</p>
  </>}
 </section>;
}
