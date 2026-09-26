'use strict';
const $=s=>document.querySelector(s);
const escapeHTML=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const STORAGE='giik.card-workshop.v1';
let meta, state={version:1,cards:[],selected:null,batch:null,teacher:''}, filter='all', generating=false, stopRequested=false, reviewing=false, storageOK=true;
const selected=()=>state.cards.find(c=>c.id===state.selected);
const date=v=>v?new Date(v).toLocaleString('ru-RU'):'—';
function notify(message,error=false){$('#notice').hidden=!message;$('#notice').textContent=message;$('#notice').classList.toggle('error',error);}
function storageWarning(message){$('#storage-warning').hidden=false;$('#storage-warning').textContent=message;}
function persist(){
 if(!storageOK)return false;
 try{localStorage.setItem(STORAGE,JSON.stringify(state));return true;}
 catch(e){storageWarning('Браузер не смог сохранить изменения. Карточки остаются на экране: скачайте JSON до закрытия вкладки.');return false;}
}
async function api(action,payload={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),110000);
 try{
  const r=await fetch('/api',{method:'POST',headers:{'Content-Type':'application/json','X-UI-Token':$('meta[name=ui-token]').content},body:JSON.stringify({action,payload}),signal:controller.signal});
  let data;try{data=await r.json();}catch{throw Error('Сервер вернул некорректный ответ. Готовые карточки остаются в браузере.');}
  if(!r.ok||data.error)throw Error(data.error||'Не удалось выполнить запрос.');
  return data.result;
 }catch(e){if(e.name==='AbortError')throw Error('Время ожидания ГигаЧата истекло. Можно продолжить с этой позиции.');throw e;}
 finally{clearTimeout(timer);}
}
function emptyContent(){return {title:'Новая карточка',report:'',fields:Object.fromEntries(Object.values(meta.groups).flatMap(([,fields])=>Object.keys(fields).map(k=>[k,'']))),class_ids:[],services:[],main_service:''};}
function addCard(content,provenance){
 const at=new Date().toISOString(), id=crypto.randomUUID();
 const record={id,number:'К-'+id.slice(0,8).toUpperCase(),status:'draft',created_at:at,updated_at:at,revision:1,content,provenance,review:null,history:[{at,action:'created',text:provenance.source==='gigachat'?'Создано ГигаЧатом':'Создано вручную'}]};
 state.cards.unshift(record);if(!state.selected)state.selected=id;return record;
}
function touch(card){card.updated_at=new Date().toISOString();card.revision++;persist();renderList();}
function renderStats(){
 const approved=state.cards.filter(c=>c.status==='approved').length;
 $('#stats').innerHTML=[[state.cards.length,'Всего карточек'],[state.cards.length-approved,'На проверке'],[approved,'Утверждено']].map(([n,label])=>`<div class="stat"><strong>${n}</strong><span>${label}</span></div>`).join('');
 $('#export-all').disabled=!state.cards.length;
}
function renderList(){
 renderStats();const query=$('#search').value.toLocaleLowerCase();
 const list=state.cards.filter(c=>(filter==='all'||c.status===filter)&&`${c.number} ${c.content.title} ${c.content.fields.city} ${c.content.fields.street} ${c.content.fields.house} ${c.content.fields.address_text}`.toLocaleLowerCase().includes(query));
 $('#card-list').innerHTML=list.map(c=>`<button class="card-item ${c.id===state.selected?'selected':''}" data-id="${escapeHTML(c.id)}" aria-pressed="${c.id===state.selected}"><span class="card-meta"><span>${escapeHTML(c.number)}</span><span class="badge ${c.status}">${c.status==='approved'?'Утверждена':'Черновик'}</span></span><strong>${escapeHTML(c.content.title||'Без названия')}</strong><p>${escapeHTML(c.content.fields.address_text||[c.content.fields.city,c.content.fields.street,c.content.fields.house].filter(Boolean).join(', ')||'Адрес не заполнен')}</p></button>`).join('')||'<p class="empty-list">Пока нет карточек по этому фильтру.</p>';
}
function field(key,label,value){
 const multiline=['address_text','access','description','people','injured','extra_signs','vis_info','control_notes'].includes(key);
 return `<label class="field ${['address_text','access','description','control_notes','vis_info'].includes(key)?'wide':''}" for="f-${key}">${escapeHTML(label)}${multiline?`<textarea id="f-${key}" data-field="${key}" maxlength="3000" rows="2">${escapeHTML(value)}</textarea>`:`<input id="f-${key}" data-field="${key}" maxlength="3000" ${key==='control_at'?'type="datetime-local"':''} value="${escapeHTML(value)}">`}</label>`;
}
function renderEditor(){
 const card=selected();if(!card)return;
 const c=card.content, locked=card.status==='approved';
 const sections=Object.entries(meta.groups).map(([key,[label,fields]],index)=>{
  const secondary=key==='address'?['country','region','object','district','area','block','building','intercom','latitude','longitude']:key==='caller'?['phone_aon','phone_scene']:key==='incident'?['vis_info','extra_signs']:[];
  const renderFields=keys=>`<div class="field-grid">${keys.map(k=>field(k,fields[k],c.fields[k])).join('')}</div>`;
  const main=Object.keys(fields).filter(k=>!secondary.includes(k));
  const body=renderFields(main)+(secondary.length?`<details><summary>${key==='address'?'Полный адрес и координаты':key==='caller'?'АОН и телефон на месте':'Дополнительные сведения'}</summary><div class="details-body">${renderFields(secondary)}</div></details>`:'');
  return key==='registration'?`<section class="card-section"><details><summary>Регистрация и контроль</summary><div class="details-body">${body}</div></details></section>`:`<section class="card-section"><div class="section-head"><span>0${index+2}</span><h3>${escapeHTML(label)}</h3></div>${body}${key==='address'?'<p class="source-note">Проверка по Яндексу и карта пока не подключены. Координаты ИИ не придумывает.</p>':''}</section>`;
 });
 $('#editor').innerHTML=`<div class="editor-head"><div class="headline"><small>${escapeHTML(card.number)} · версия ${card.revision}</small><span class="badge ${card.status}">${locked?'Утверждена преподавателем':'На проверке'}</span></div><label for="card-title" class="sr-only">Название карточки</label><input id="card-title" maxlength="160" value="${escapeHTML(c.title)}" ${locked?'readonly':''}><p class="source-note">Создана ${date(card.created_at)} · ${card.provenance.source==='gigachat'?'GigaChat · вымышленные данные':'Заполнена вручную'} · сохранена ${date(card.updated_at)}</p></div>
 <div class="editor-body"><fieldset id="content-fields" ${locked?'disabled':''}>
 <section class="card-section"><div class="section-head"><span>01</span><h3>Исходное сообщение заявителя</h3></div><label for="report" class="sr-only">Сообщение заявителя</label><textarea id="report" maxlength="6000" rows="4">${escapeHTML(c.report)}</textarea><p class="source-note">Сверьте поля с этим сообщением. Неизвестные сведения не означают отсутствие людей или пострадавших.</p></section>
 ${sections.slice(0,2).join('')}
 <section class="card-section"><h3>Классификация происшествия</h3><div class="choices">${meta.catalog.map(x=>`<label class="choice"><input type="checkbox" data-class="${x.id}" ${c.class_ids.includes(x.id)?'checked':''}><span>${escapeHTML(x.title)}<small>${escapeHTML(x.group)} · ${escapeHTML(x.sign1)} → ${escapeHTML(x.sign2)} → ${escapeHTML(x.sign3)}<br>Демо-код: ${escapeHTML(x.id)}</small></span></label>`).join('')}</div><p class="source-note">Можно выбрать несколько типов. Это демонстрационный набор, не официальный классификатор 112.</p></section>
 ${sections.slice(2).join('')}
 <section class="card-section"><h3>Предлагаемые службы</h3><div class="choices services">${Object.entries(meta.services).map(([code,label])=>`<label class="choice"><input type="checkbox" data-service="${code}" ${c.services.includes(code)?'checked':''}><span>${code} · ${escapeHTML(label)}</span></label>`).join('')}</div><label style="margin-top:14px">Главная служба<select id="main-service"><option value="">Не выбрана</option>${Object.entries(meta.services).map(([code,label])=>`<option value="${code}" ${c.main_service===code?'selected':''}>${code} · ${escapeHTML(label)}</option>`).join('')}</select></label><p class="source-note">Состав проверяет преподаватель. Выбор службы не означает отправку карточки или вызов экипажа.</p></section></fieldset>
 <section class="review-box ${locked?'approved':''}"><h3>${locked?'Карточка утверждена':'Проверка преподавателем'}</h3>${locked?`<p class="review-meta">${escapeHTML(card.review.teacher)} · ${date(card.review.at)}</p><p>${escapeHTML(card.review.note||'Без замечаний')}</p><div class="review-actions"><button id="reopen">Вернуть на доработку</button><button id="export-one">Скачать карточку</button></div>`:`<p>Проверьте адрес, описание, признаки и состав служб. После утверждения карточка будет защищена от случайных правок.</p><div class="field-grid"><label>Преподаватель<input id="teacher" maxlength="160" placeholder="Ваше имя" value="${escapeHTML(state.teacher)}"></label><label>Комментарий<input id="review-note" maxlength="3000" value="${escapeHTML(card.review_note||'')}" placeholder="Необязательно"></label></div><div class="review-actions"><button id="validate">Проверить поля</button><button id="approve" class="primary">Утвердить карточку</button><button id="export-one">Скачать</button></div>`}</section>
 <details><summary>История карточки · ${card.history.length}</summary>${card.history.slice().reverse().map(h=>`<div class="history-row">${date(h.at)} · ${escapeHTML(h.text)}</div>`).join('')}</details><p class="footer-note">Правки сохраняются автоматически в этом браузере. Утверждение здесь — отметка локального прототипа, без проверки учётной записи.</p></div>`;
 $('#editor').inert=reviewing;
}
function renderProgress(){
 const b=state.batch;$('#progress-panel').hidden=!b;
 if(b){
  $('#progress').max=b.total;$('#progress').value=b.done;
  const suffix=b.done>=b.total?'Подборка готова':b.status==='error'?'Ошибка — можно повторить':b.status==='paused'?'Приостановлено':stopRequested?'Останавливаем после текущей карточки':`Создаётся карточка ${b.done+1}`;
  $('#progress-text').textContent=`Готово ${b.done} из ${b.total} · ${suffix}`;
  $('#stop').hidden=!generating;$('#stop').disabled=stopRequested;
  $('#resume').hidden=generating||b.done>=b.total;
 }
 for(const el of $('#generate-form').elements)el.disabled=generating||reviewing;
 $('#resume').disabled=reviewing;
}
function download(records,name){
 const blob=new Blob([JSON.stringify({format:'giik-incident-cards',version:1,exported_at:new Date().toISOString(),catalog_version:'demo-v1',catalog:meta.catalog,cards:records},null,2)],{type:'application/json;charset=utf-8'});
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function generateBatch(){
 if(generating||reviewing)return;generating=true;stopRequested=false;notify('');
 const batch=state.batch;batch.status='running';persist();renderProgress();
 try{
  while(batch.done<batch.total&&!stopRequested){
   const result=await api('card_generate',{topic:batch.topic,category:batch.category,index:batch.done+1,total:batch.total,recent_titles:state.cards.slice(0,10).map(c=>c.content.title)});
   addCard(result.content,{source:'gigachat',model:result.model,prompt_version:result.prompt_version,catalog_version:result.catalog_version,generated_at:result.generated_at});
   batch.done++;persist();renderList();if(!$('#card-title'))renderEditor();renderProgress();
  }
  batch.status=batch.done===batch.total?'done':'paused';
  notify(batch.status==='done'?`Готово. Создано карточек: ${batch.done}. Теперь их можно проверить и утвердить.`:`Генерация остановлена. Сохранено ${batch.done} из ${batch.total} карточек.`);
 }catch(e){batch.status='error';notify(e.message,true);}
 finally{generating=false;persist();renderProgress();}
}
$('#generate-form').addEventListener('submit',e=>{
 e.preventDefault();if(generating||reviewing)return;
 const total=Number($('#count').value);if(!Number.isInteger(total)||total<1||total>100){notify('Укажите от 1 до 100 карточек.',true);return;}
 if(state.batch&&state.batch.done<state.batch.total&&!confirm('Заменить незавершённую очередь новой? Уже созданные карточки останутся.'))return;
 filter='all';$('#search').value='';document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter==='all'));renderList();
 state.batch={topic:$('#topic').value,category:$('#category').value,total,done:0,status:'running'};generateBatch();
});
$('#stop').addEventListener('click',()=>{stopRequested=true;renderProgress();});
$('#resume').addEventListener('click',()=>{if(state.batch?.done<state.batch?.total)generateBatch();});
$('#new-card').addEventListener('click',()=>{if(reviewing)return;state.selected=addCard(emptyContent(),{source:'manual'}).id;filter='all';$('#search').value='';document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter==='all'));persist();renderList();renderEditor();});
$('#search').addEventListener('input',renderList);
document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));renderList();}));
$('#card-list').addEventListener('click',e=>{const el=e.target.closest('[data-id]');if(!el||reviewing)return;state.selected=el.dataset.id;persist();renderList();renderEditor();});
$('#export-all').addEventListener('click',()=>download(state.cards,'Карточки-происшествий.json'));
$('#editor').addEventListener('input',e=>{
 const card=selected();if(!card||card.status==='approved'||reviewing)return;
 const el=e.target;if(el.id==='teacher'){state.teacher=el.value;persist();return;}
 if(el.id==='review-note'){card.review_note=el.value;persist();return;}
 if(el.dataset.field)card.content.fields[el.dataset.field]=el.value;
 else if(el.id==='card-title')card.content.title=el.value;
 else if(el.id==='report')card.content.report=el.value;
 else return;
 touch(card);
});
$('#editor').addEventListener('change',e=>{
 const card=selected();if(!card||card.status==='approved'||reviewing)return;
 const el=e.target,c=card.content;
 if(el.dataset.class)c.class_ids=[...document.querySelectorAll('[data-class]:checked')].map(x=>x.dataset.class);
 else if(el.dataset.service){c.services=[...document.querySelectorAll('[data-service]:checked')].map(x=>x.dataset.service);if(!c.services.includes(c.main_service)){c.main_service='';$('#main-service').value='';}}
 else if(el.id==='main-service'){c.main_service=el.value;if(el.value&&!c.services.includes(el.value)){c.services.push(el.value);document.querySelector(`[data-service="${el.value}"]`).checked=true;}}
 else return;touch(card);
});
$('#editor').addEventListener('click',async e=>{
 const id=e.target.closest('button')?.id,card=selected();if(!card||reviewing)return;
 if(id==='export-one'){download([card],card.number+'.json');return;}
 if(id==='reopen'){
  if(!confirm('Вернуть карточку на доработку? После изменений потребуется новое утверждение.'))return;
  card.history.push({at:new Date().toISOString(),action:'reopened',text:'Возвращена на доработку; предыдущее утверждение отменено'});
  card.status='draft';card.review=null;touch(card);renderEditor();notify('Карточка снова доступна для редактирования.');return;
 }
 if(!['validate','approve'].includes(id)||card.status!=='draft')return;
 reviewing=true;$('#editor').inert=true;$('#new-card').disabled=true;$('#generate').disabled=true;renderProgress();
 try{
  if(id==='validate'){await api('card_validate',{content:card.content});notify('Формат полей корректен. Смысл и полноту сведений проверяет преподаватель.');}
  else{
   const result=await api('card_approve',{content:card.content,teacher:state.teacher,note:card.review_note||''});
   card.content=result.content;card.review=result.review;card.status='approved';card.updated_at=result.review.at;
   card.history.push({at:result.review.at,action:'approved',text:`Утверждено: ${result.review.teacher}`,review:structuredClone(result.review),content:structuredClone(card.content)});
   persist();renderList();notify('Карточка утверждена.');
  }
 }catch(e){notify(e.message,true);}
 finally{reviewing=false;$('#new-card').disabled=false;renderProgress();renderEditor();}
});
window.addEventListener('beforeunload',e=>{if(generating||reviewing){e.preventDefault();e.returnValue='';}});
window.addEventListener('storage',e=>{if(e.key===STORAGE){storageOK=false;stopRequested=true;storageWarning('Подборка изменена в другой вкладке. Чтобы не перезаписать её, автосохранение здесь остановлено. Скачайте нужные карточки и обновите страницу.');}});
async function init(){
 try{
  meta=await api('card_meta');
  $('#category').innerHTML=Object.entries(meta.categories).map(([k,v])=>`<option value="${k}">${escapeHTML(v)}</option>`).join('');
  try{
   const raw=localStorage.getItem(STORAGE);
   if(raw){
    const saved=JSON.parse(raw),keys=Object.keys(emptyContent().fields);
    if(saved.version!==1||!Array.isArray(saved.cards)||saved.cards.some(c=>!c.id||!c.content||!c.provenance||!Array.isArray(c.history)||!['draft','approved'].includes(c.status)||(c.status==='approved'&&!c.review)||!Array.isArray(c.content.class_ids)||!Array.isArray(c.content.services)||keys.some(k=>typeof c.content.fields?.[k]!=='string')))throw Error('Неверный формат');
    state=saved;if(!state.cards.some(c=>c.id===state.selected))state.selected=state.cards[0]?.id||null;
    if(state.batch){
     if(!Number.isInteger(state.batch.total)||state.batch.total<1||state.batch.total>100||!Number.isInteger(state.batch.done)||state.batch.done<0||state.batch.done>state.batch.total||!(state.batch.category in meta.categories))state.batch=null;
     else if(state.batch.status==='running')state.batch.status='paused';
    }
   }
  }catch(e){storageOK=false;storageWarning('Не удалось прочитать сохранённую подборку. Она не перезаписана. Новые карточки можно скачать в JSON; автосохранение пока отключено.');}
  if(state.batch){$('#topic').value=state.batch.topic;$('#count').value=state.batch.total;$('#category').value=state.batch.category;}
  renderList();renderEditor();renderProgress();document.body.dataset.ready='true';
 }catch(e){notify(e.message,true);$('#generate').disabled=true;$('#new-card').disabled=true;}
}
init();
