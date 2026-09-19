// Small harness controls for the model's two workflows; no actual telephony.
function workflowOptions(id,selected='caller'){
 return `<label for="${id}">Учебный вариант</label><select id="${id}">${Object.entries(meta.workflows).map(([k,v])=>`<option value="${k}" ${k===selected?'selected':''}>${esc(v)}${id==='learn-workflow'?` · ${meta.counts[k]} карточек`:''}</option>`).join('')}</select>`;
}
function decorateSession(){
 if(session.workflow!=='dds')return;
 const s=session, active=s.status==='active', connected=s.dds.connection==='connected';
 const left=$('#chat').closest('section');left.querySelector('h2').textContent='Разговор со службой';
 left.querySelector('.pill').textContent=({idle:'Звонок не начат',connected:'Служба на линии',disconnected:'Обрыв связи',ended:'Звонок завершён'})[s.dds.connection];
 if(active){
  $('#question').placeholder='Представьтесь и передайте сведения по карточке';
  $('label[for=question]').textContent='Ваша реплика службе';
  $('#question-form button[type=button][data-cmd=mic]').disabled=!connected;
  $('#question-form button:not([type])').disabled=!connected;
  $('#question').disabled=!connected;
 }
 const panel=document.createElement('div');panel.className='hint';
 panel.innerHTML=`<b>${esc(s.dds.service_name)}</b><p>Текстовая имитация разговора. Реальных звонков нет.</p>${active?`<div class="actions"><button data-cmd="connect-service" ${connected?'disabled':''}>${s.dds.attempts?'Перезвонить службе':'Позвонить службе'}</button><button class="secondary" data-cmd="end-service" ${!connected?'disabled':''}>Завершить звонок</button></div>${connected?`<label for="next-channel">Для проверки модели: связь на следующей реплике</label><select id="next-channel"><option value="clear" ${s.dds.next_channel==='clear'?'selected':''}>Без помех</option><option value="partial" ${s.dds.next_channel==='partial'?'selected':''}>Слышно только начало фразы</option><option value="drop" ${s.dds.next_channel==='drop'?'selected':''}>Обрыв: фраза не доставлена</option></select>`:''}`:''}`;
 $('#chat').before(panel);
 const right=$('#card-fields').closest('section');right.querySelector('h2').textContent='Полученная карточка 112';
 right.querySelector('p.muted').textContent='Проверьте сведения по доступному уточнению и внесите исправления.';
 const reference=document.createElement('details');reference.open=true;
 reference.innerHTML=`<summary>Доступное уточнение от 112</summary><p>${esc(s.dds.verification_notes)}</p><details><summary>Исходная карточка до ваших исправлений</summary>${Object.entries(s.dds.incoming_card).map(([k,v])=>`<p><b>${esc(meta.fields[k])}:</b> ${esc(v)}</p>`).join('')}</details>`;
 $('#card-fields').before(reference);
}
function decorateTask(){
 if(task.workflow!=='dds')return;
 $('label[for=task-opening]').textContent='Задание диспетчеру ДДС';
 $('label[for=task-persona]').textContent='Поведение представителя службы';
 $('#task-editor').insertAdjacentHTML('beforeend',`<details open><summary>Входящая карточка и условия варианта ДДС</summary><p class="muted">Условия учебные. Проверьте обнаруживаемость ошибок и критерии перед утверждением.</p>${Object.entries(meta.fields).map(([k,label])=>area('Исходное поле: '+label,'dds-card-'+k,task.incoming_card[k],'maxlength="2000"')).join('')}${area('Доступное ученику уточнение / исходное сообщение','dds-verification',task.verification_notes)}${area('Заложенные ошибки — только преподавателю','dds-faults',task.faults)}${input('Название учебной службы','dds-service-name',task.service.name)}${input('Роль собеседника','dds-service-role',task.service.role)}${area('Что сотрудник знает ДО звонка (без скрытого адреса и эталона)','dds-service-knowledge',task.service.knowledge)}${Object.entries(meta.action_labels).map(([k,label])=>`<details><summary>${esc(label)}</summary>${area('Ожидаемое действие','dds-'+k+'-expected',task.actions[k].expected)}${area('Критерий проверки','dds-'+k+'-criterion',task.actions[k].criterion)}</details>`).join('')}</details>`);
}
function collectDDS(){
 if(task.workflow!=='dds')return {};
 return {incoming_card:Object.fromEntries(Object.keys(meta.fields).map(k=>[k,$('#dds-card-'+k).value])),verification_notes:$('#dds-verification').value,
 faults:$('#dds-faults').value,service:{name:$('#dds-service-name').value,role:$('#dds-service-role').value,knowledge:$('#dds-service-knowledge').value},
 actions:Object.fromEntries(Object.keys(meta.action_labels).map(k=>[k,{expected:$('#dds-'+k+'-expected').value,criterion:$('#dds-'+k+'-criterion').value}]))};
}
function reviewLabels(){return review?.task.workflow==='dds'?{...meta.fields,...meta.action_labels}:meta.fields;}
