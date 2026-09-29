import {ADDRESS_KEYS,LOCATION_KEYS,addressFields} from './address-search.js';
import {api,attachToken} from './api.js';
import {adminSignedIn,accessToken} from './admin-auth.js';
import {syncServices,chooseService} from './service-routing.js';
import {referenceCurrent} from './reference-state.js';
import {ensureCallerId,prepareCaller} from './telephony.js';
export const STORAGE='giik.card-workshop.v1';
const teacherProfile=()=>{try{return JSON.parse(localStorage.getItem('giik.teacher.profile.v1'))?.name?.trim()||'Преподаватель';}catch{return 'Преподаватель';}};
// Keep the existing version-1 browser format, including approved historical snapshots.
export function createWorkshopStore(){
 let state={version:1,cards:[],selected:null,batch:null,teacher:''},meta=null,ready=false;
 let generating=false,reviewing=false,referencePending=null,stopRequested=false,storageOK=true,warning='',notice='',error=false;
 const listeners=new Set();let snapshot;
 const emit=()=>{snapshot={state,meta,ready,generating,reviewing,referencePending,stopRequested,warning,notice,error};listeners.forEach(fn=>fn());};
 const notify=(text,isError=false)=>{notice=text;error=isError;emit();};
 // Этап 5: мастерская читает/пишет PostgreSQL через /workshop/* (JWT teacher/admin).
 let serverMode=false;const dirty=new Set();
 const serverSync=async()=>{if(!serverMode)return;const pending=[...dirty];dirty.clear();
  for(const number of pending){const card=state.cards.find(c=>c.number===number);if(!card)continue;
   try{await api('workshop_cards_update',{workshop_ref:number,content:card});}
   catch{try{await api('workshop_cards_create',{content:card});}catch{}}}}
 const persist=()=>{if(!storageOK)return false;try{localStorage.setItem(STORAGE,JSON.stringify(state));if(serverMode){const current=selected();if(current)dirty.add(current.number);serverSync();}return true;}catch{warning='Браузер не смог сохранить изменения. Скачайте JSON до закрытия вкладки.';return false;}};
 const selected=()=>state.cards.find(c=>c.id===state.selected);
 const touch=card=>{card.updated_at=new Date().toISOString();card.revision++;card.reference_checked=false;if(serverMode)dirty.add(card.number);persist();emit();};
 const empty=()=>({title:'Новая карточка',report:'',fields:Object.fromEntries(Object.values(meta.groups).flatMap(([,fields])=>Object.keys(fields).map(k=>[k,'']))),class_ids:[],services:[],main_service:'',flags:{}});
 function add(content,provenance){const at=new Date().toISOString(),id=crypto.randomUUID();const card={id,number:'К-'+id.slice(0,8).toUpperCase(),status:'draft',created_at:at,updated_at:at,revision:1,content,provenance,review:null,history:[{at,action:'created',text:['ai','gigachat'].includes(provenance.source)?'Создано ИИ':'Создано вручную'}]};ensureCallerId(card,true);prepareCaller(card);card.content.fields.phone_callback='';syncServices(meta,card);state.cards.unshift(card);if(!state.selected)state.selected=id;if(serverMode)dirty.add(card.number);return card;}
 async function init(){try{
  meta=await api('card_meta');
  try{const raw=localStorage.getItem(STORAGE);if(raw){const saved=JSON.parse(raw),keys=Object.keys(empty().fields);
   if(saved.version!==1||!Array.isArray(saved.cards)||saved.cards.some(c=>!c.id||!c.content||!c.provenance||!Array.isArray(c.history)||!['draft','approved'].includes(c.status)||(c.status==='approved'&&!c.review)||!Array.isArray(c.content.class_ids)||!Array.isArray(c.content.services)||keys.some(k=>typeof c.content.fields?.[k]!=='string')))throw Error('Неверный формат');
   state=saved;if(!selected())state.selected=state.cards[0]?.id||null;
   if(state.batch){const b=state.batch;if(!Number.isInteger(b.total)||b.total<1||b.total>100||!Number.isInteger(b.done)||b.done<0||b.done>b.total||!(b.category in meta.categories)&&!['fire','road','medical','gas'].includes(b.category))state.batch=null;else {b.category=({fire:'1',road:'2',medical:'22',gas:'13'})[b.category]||b.category;if(b.status==='running')b.status='paused';}}
  }}catch{storageOK=false;warning='Не удалось прочитать сохранённую подборку. Она не перезаписана. Новые карточки можно скачать в JSON; автосохранение отключено.';}
  if(!state.teacher?.trim())state.teacher=teacherProfile();
  if(storageOK){const before=JSON.stringify(state.cards);state.cards.forEach(card=>{let changed=false;const at=new Date().toISOString();if(ensureCallerId(card)){changed=true;card.history.push({at,action:'caller_id_simulated',text:'Добавлен условный номер входящего звонка (АОН)'});}if(card.status==='draft'&&!card.caller_scenario){prepareCaller(card);changed=true;card.history.push({at,action:'caller_scenario_migrated',text:'Подготовлен сценарий заявителя для выделенного REST-диалога; эталон требуется обновить'});}if(changed){card.updated_at=at;card.revision=(card.revision||0)+1;card.reference_checked=false;}syncServices(meta,card);});if(before!==JSON.stringify(state.cards))persist();}
  if(storageOK){for(const card of state.cards.filter(c=>c.status==='approved'&&!c.training_task_id&&c.caller_scenario&&c.reference)){try{const published=await api('card_publish',{content:card.content,reference:card.reference,caller_scenario:card.caller_scenario,reference_checked:true,teacher:card.review.teacher,note:card.review.note||'',level:'medium',opening:card.training_opening||undefined});card.training_task_id=published.task_id;}catch{warning='Некоторые ранее утверждённые карточки не добавлены в тренировки. Откройте карточку и нажмите «Добавить в тренировки обучающегося».';}}persist();}
  // Этап 5: мастерская из PostgreSQL (JWT преподавателя), localStorage — кэш.
  serverMode=adminSignedIn();
  if(serverMode){attachToken(accessToken());
   try{const brief=await api('workshop_cards_list');
    if(brief.length){const cards=[];
     for(const row of brief){try{cards.push(await api('workshop_cards_get',{workshop_ref:row.number}));}catch{}}
     if(cards.length){state.cards=cards;if(!state.selected)state.selected=cards[0]?.id||null;persist();}}
    const raw=localStorage.getItem(STORAGE);
    if(raw){const local=JSON.parse(raw);
     if(local&&Array.isArray(local.cards)&&local.cards.length){
      try{const result=await api('workshop_import',{cards:local.cards});
       if(result&&result.imported)notice=`Перенесено в БД карточек: ${result.imported}.`;}catch{}}}
   }catch{serverMode=false;}}
  ready=true;emit();
 }catch(e){notify(e.message,true);}}
 async function buildReference(card){
  referencePending=card.id;card.reference_error='';persist();emit();
  try{const reference=await api('card_reference',{content:structuredClone(card.content),caller_scenario:card.caller_scenario});
   if(card.reference)card.history.push({at:new Date().toISOString(),action:'reference_replaced',text:'Предыдущая версия эталона сохранена',reference:structuredClone(card.reference)});
   card.reference=reference;touch(card);return true;
  }catch(e){card.reference_error=e.message;persist();emit();return false;}
  finally{referencePending=null;emit();}
 }
 async function generateReference(){const card=selected();if(!card||card.status==='approved'||generating||reviewing)return;reviewing=true;emit();try{const ok=await buildReference(card);notify(ok?'Эталон создан. Проверьте ответ и подтвердите его перед утверждением.':card.reference_error,!ok);}finally{reviewing=false;emit();}}
 async function generate(){if(generating||reviewing||!state.batch)return;generating=true;stopRequested=false;notice='';const b=state.batch;b.status='running';persist();emit();
  try{while(b.done<b.total&&!stopRequested){const result=await api('card_generate',{topic:b.topic,category:b.category,classification:b.classification||{},flags:b.flags||{},location:b.location||'Учебный город',index:b.done+1,total:b.total,recent_titles:state.cards.slice(0,10).map(c=>c.content.title)});const created=add(result.content,{source:'ai',model:result.model,prompt_version:result.prompt_version,catalog_version:result.catalog_version,generated_at:result.generated_at});b.done++;persist();emit();await buildReference(created);}
   b.status=b.done===b.total?'done':'paused';notify(b.status==='done'?`Готово. Создано карточек: ${b.done}. Проверьте карточки и эталоны. Требуют обновления эталона: ${state.cards.filter(c=>c.status!=='approved'&&!referenceCurrent(c)).length}.`:`Генерация остановлена. Сохранено ${b.done} из ${b.total} карточек.`);
  }catch(e){b.status='error';notify(e.message,true);}finally{generating=false;persist();emit();}
 }
 async function review(action){const card=selected();if(!card||reviewing||generating||card.status!=='draft')return;reviewing=true;emit();try{
  if(action==='validate'){await api('card_validate',{content:card.content});notify('Формат полей корректен. Смысл и полноту сведений проверяет преподаватель.');}
  else{const approval={content:card.content,caller_scenario:card.caller_scenario,reference:card.reference,reference_checked:card.reference_checked===true,teacher:state.teacher||teacherProfile(),note:card.review_note||'',level:'medium',opening:card.training_opening||undefined};const result=await api('card_approve',approval);card.content=result.content;card.reference=result.reference;card.review=result.review;card.status='approved';card.updated_at=result.review.at;card.history.push({at:result.review.at,action:'approved',text:`Утверждено: ${result.review.teacher}`,review:structuredClone(result.review),content:structuredClone(card.content),reference:structuredClone(card.reference)});persist();try{const published=await api('card_publish',{...approval,content:result.content,reference:result.reference,reference_checked:true,teacher:result.review.teacher,note:result.review.note||''});card.training_task_id=published.task_id;delete card.training_publish_error;persist();notify('Карточка и эталон утверждены и добавлены в тренировки.');}catch(publishError){card.training_publish_error=publishError.message;warning='Карточка утверждена, но пока не добавлена в тренировки: '+publishError.message;persist();notify('Карточка и эталон утверждены. Публикацию можно повторить отдельной кнопкой.');}}
 }catch(e){notify(e.message,true);}finally{reviewing=false;emit();}}
 function edit(kind,key,value){const card=selected();if(!card||card.status==='approved'||reviewing)return;
  if(kind==='reference_checked'){card.reference_checked=value&&referenceCurrent(card);persist();emit();return;}
  if(kind==='teacher'){state.teacher=value;persist();emit();return;}
  if(kind==='note'){card.review_note=value;persist();emit();return;}
  if(kind==='training'){card[key]=value;touch(card);return;}
  const c=card.content;
  if(kind==='flag'){c.flags={...(c.flags||{}),[key]:value};}
  else if(kind==='field'){if(key==='phone_aon'||key==='phone_callback'&&card.caller_scenario&&!card.caller_dialogue?.callback_disclosed)return;if(LOCATION_KEYS.includes(key)&&c.fields[key]!==value){c.fields.latitude='';c.fields.longitude='';card.geocoding=null;}if(['latitude','longitude'].includes(key))card.geocoding=null;c.fields[key]=value;}
  else if(kind==='content'){c[key]=value;if(key==='report'&&card.caller_scenario)card.caller_dialogue={turns:[],callback_disclosed:false};}
  else if(kind==='class_ids'){c.class_ids=value?Array.from(new Set([...c.class_ids,key])):c.class_ids.filter(x=>x!==key);}
  else if(kind==='services'){chooseService(meta,card,key,value);}
  else if(kind==='main_service'){if(value)chooseService(meta,card,value,true);c.main_service=value;}
  if(kind==='class_ids'||kind==='flag')syncServices(meta,card);
  touch(card);
 }
 async function askCaller(question){
  const card=selected();if(!card?.caller_scenario||reviewing||generating)return false;
  reviewing=true;emit();
  try{const dialogue=card.caller_dialogue||{turns:[],callback_disclosed:false};
   const result=await api('card_caller',{content:card.content,caller_scenario:card.caller_scenario,turns:dialogue.turns,question});
   card.caller_dialogue={turns:[...dialogue.turns,{role:'dispatcher',text:question.trim()},{role:'caller',text:result.reply}],callback_disclosed:dialogue.callback_disclosed||result.callback_disclosed};
   persist();notify('Заявитель ответил. Внесите полученные сведения в карточку самостоятельно.');return true;
  }catch(e){notify(e.message,true);return false;}finally{reviewing=false;emit();}
 }
 function download(records,name){const blob=new Blob([JSON.stringify({format:'giik-incident-cards',version:1,exported_at:new Date().toISOString(),catalog_version:meta.catalog_version,catalog:meta.catalog,cards:records},null,2)],{type:'application/json;charset=utf-8'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 function onStorage(e){if(e.key===STORAGE){storageOK=false;stopRequested=true;warning='Подборка изменена в другой вкладке. Автосохранение остановлено. Скачайте нужные карточки и обновите страницу.';emit();}}
 function onUnload(e){if(generating||reviewing){e.preventDefault();e.returnValue='';}}
 emit();return {
  subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);},getSnapshot:()=>snapshot,
  init,edit,review,notify,generateReference,askCaller,
  async publishTraining(){const card=selected();if(!card||card.status!=='approved'||reviewing)return;reviewing=true;emit();try{const result=await api('card_publish',{content:card.content,reference:card.reference,caller_scenario:card.caller_scenario,reference_checked:true,teacher:card.review.teacher,note:card.review.note||'',level:'medium',opening:card.training_opening||undefined});card.training_task_id=result.task_id;delete card.training_publish_error;persist();notify('Карточка доступна обучающемуся в списке тренировок.');}catch(e){card.training_publish_error=e.message;persist();notify('Карточка утверждена, но публикация в тренировки не выполнена: '+e.message,true);}finally{reviewing=false;emit();}},
  selectAddress(record,context){const card=selected();if(!card||card.status==='approved'||reviewing)return;Object.assign(card.content.fields,Object.fromEntries(ADDRESS_KEYS.map(k=>[k,''])),addressFields(record,context));card.geocoding={source:'OpenStreetMap',id:record.id,kind:record.kind,point:record.point,selected_at:new Date().toISOString()};card.history.push({at:new Date().toISOString(),action:'address_selected',text:'Выбран адрес OSM: '+record.street+' '+record.house});touch(card);},
  clearAddress(){const card=selected();if(!card||card.status==='approved'||reviewing)return;Object.assign(card.content.fields,Object.fromEntries([...ADDRESS_KEYS,'latitude','longitude'].map(k=>[k,''])));card.geocoding=null;touch(card);},
  prepareCaller(){const card=selected();if(!card||card.status==='approved'||reviewing||generating||card.caller_scenario)return;prepareCaller(card);touch(card);notify('Разговор подготовлен. Обновите эталон: в нём появится телефон заявителя.');},
  resetCaller(){const card=selected();if(!card||reviewing||generating)return;card.caller_dialogue={turns:[],callback_disclosed:false};persist();emit();},
  replaceClass(previous,next){const card=selected();if(!card||card.status==='approved'||reviewing||!meta.catalog.some(x=>x.id===next))return;card.content.class_ids=[...new Set(card.content.class_ids.map(id=>id===previous?next:id).concat(previous?[]:[next]))];syncServices(meta,card);touch(card);},
  editReference(section,key,value,part='value'){const card=selected();if(!card?.reference||card.status==='approved'||reviewing||generating)return;const answer=card.reference.answer;if(section==='expected_fields')answer.expected_fields[key][part]=value;else if(section==='questions'||section==='critical_errors')answer[section]=value;else answer[section]=value;card.reference.edited_at=new Date().toISOString();touch(card);},
  setServices(codes){const card=selected();if(!card||card.status==='approved'||reviewing)return;const wanted=new Set(codes.filter(code=>code in meta.services));const previous=[...card.content.services];for(const code of new Set([...previous,...wanted])){if(previous.includes(code)!==wanted.has(code))chooseService(meta,card,code,wanted.has(code));}touch(card);},
  resetServices(){const card=selected();if(!card||card.status==='approved'||reviewing)return;card.service_selection={version:1,added:[],removed:[]};syncServices(meta,card);touch(card);notify('Состав служб восстановлен по классификатору.');},
  saveCurrent(){if(!selected()||reviewing)return;const ok=persist();notify(ok?'Карточка сохранена в этом браузере.':'Не удалось сохранить карточку. Скачайте JSON до закрытия вкладки.',!ok);},
  attach(){window.addEventListener('storage',onStorage);window.addEventListener('beforeunload',onUnload);return()=>{window.removeEventListener('storage',onStorage);window.removeEventListener('beforeunload',onUnload);};},
  start(params){if(generating||reviewing)return false;if(!Number.isInteger(params.total)||params.total<1||params.total>100){notify('Укажите от 1 до 100 карточек.',true);return false;}if(state.batch&&state.batch.done<state.batch.total&&!confirm('Заменить незавершённую очередь новой? Уже созданные карточки останутся.'))return false;state.batch={...params,done:0,status:'running'};generate();return true;},
  resume:generate,stop(){stopRequested=true;emit();},
  addManual(){if(!ready||reviewing)return;state.selected=add(empty(),{source:'manual'}).id;persist();emit();},
  select(id){if(reviewing)return;state.selected=id;persist();emit();},
  reopen(){const card=selected();if(!card||reviewing||!confirm('Вернуть карточку на доработку? После изменений потребуется новое утверждение.'))return;card.history.push({at:new Date().toISOString(),action:'reopened',text:'Возвращена на доработку; предыдущее утверждение отменено'});card.status='draft';card.review=null;if(!card.caller_scenario)prepareCaller(card);syncServices(meta,card);touch(card);notify('Карточка снова доступна для редактирования.');},
  exportAll(){download(state.cards,'Карточки-происшествий.json');},exportOne(){const c=selected();if(c)download([c],c.number+'.json');}
 };
}
