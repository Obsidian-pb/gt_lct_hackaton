// The source uses explicit columns for variants of a service. Unknown facts are
// not negative facts: only the source's "flag not selected" variant uses !yes.
export function recommendServices(meta,content){
 const flags=content.flags||{},yes=k=>flags[k]==='yes',none=keys=>keys.every(k=>!yes(k));
 const matches={N:!yes('no_access'),O:yes('no_access'),P:none(['threat','injured','no_access']),
  Q:yes('threat'),R:yes('injured'),S:yes('no_access'),T:true,
  U:none(['offence','injured']),V:yes('offence'),W:yes('injured'),
  X:none(['injured','not_on_scene']),Y:yes('injured')&&!yes('not_on_scene'),Z:yes('injured')&&yes('not_on_scene'),
  AA:!yes('gas'),AB:yes('gas'),AC:none(['threat','injured','medical','evacuation']),
  AD:yes('threat'),AE:yes('injured'),AF:yes('medical'),AG:yes('evacuation'),
  AM:yes('injured'),AU:true};
 const services=new Set(),reasons={},pending=[];
 const catalog=[...meta.catalog,...(meta.legacy_catalog||[])];
 for(const id of content.class_ids){
  const entry=catalog.find(x=>x.id===id);if(!entry)continue;
  const selected=new Map((entry.services||[]).map(code=>[code,[`Главная служба · ${entry.id}`]])),blocked=new Set();
  for(const rule of entry.rules||[]){
   const applies=rule.condition===''?true:rule.column==='CI'?entry.category==='1':matches[rule.column];
   if(applies===undefined){pending.push({...rule,class_id:id,source_row:entry.source_row});continue;}
   if(!applies)continue;
   if(rule.value.trim().toLowerCase()==='нет реагирования'){blocked.add(rule.service);continue;}
   if(!rule.value.trim())continue;
   const evidence=`${rule.column}${entry.source_row}: ${rule.condition||'Без отдельного условия'} — ${rule.value}`;
   selected.set(rule.service,[...(selected.get(rule.service)||[]),evidence]);
  }
  for(const [code,evidence] of selected){if(blocked.has(code))continue;services.add(code);reasons[code]=[...(reasons[code]||[]),...evidence];}
 }
 return {services:[...services],reasons,pending};
}

// Recalculate the student's automatic routing while preserving the choices the
// student made manually. Overrides can be reconstructed from the card itself,
// so they also survive a draft round-trip through localStorage/server storage.
export function syncLearnerServices(meta,previous,next){
 const before=recommendServices(meta,previous).services;
 const after=recommendServices(meta,next).services;
 const beforeSet=new Set(before),selected=new Set(previous.services||[]);
 const manualAdded=[...selected].filter(code=>!beforeSet.has(code));
 const manualRemoved=before.filter(code=>!selected.has(code));
 const removed=new Set(manualRemoved);
 next.services=[...new Set([...after,...manualAdded])].filter(code=>!removed.has(code));
 if(next.main_service&&!next.services.includes(next.main_service))next.main_service='';
 if(!next.main_service){
  const catalog=[...meta.catalog,...(meta.legacy_catalog||[])];
  const primary=[...new Set(catalog.filter(x=>next.class_ids.includes(x.id)).flatMap(x=>x.services||[]))].filter(code=>next.services.includes(code));
  if(primary.length===1)next.main_service=primary[0];
  else if(next.services.length===1)next.main_service=next.services[0];
 }
 return next;
}

export function learnerServiceOrigin(meta,content,code){
 const automatic=new Set(recommendServices(meta,content).services);
 return automatic.has(code)?'По классификатору':'Добавлено обучающимся';
}

// Kept outside content: the server's card contract stays unchanged. Approved
// versions are never recalculated. Old draft extras become teacher additions.
export function syncServices(meta,card){
 if(card.status==='approved')return;
 const c=card.content,auto=recommendServices(meta,c);
 if(!card.service_selection){
  const catalog=[...meta.catalog,...(meta.legacy_catalog||[])];
  const previousBase=new Set(c.class_ids.flatMap(id=>catalog.find(x=>x.id===id)?.services||[]));
  card.service_selection={version:1,added:c.services.filter(code=>!previousBase.has(code)),removed:[]};
 }
 const choice=card.service_selection;
 c.services=[...new Set([...auto.services,...choice.added])].filter(code=>!choice.removed.includes(code));
 if(c.main_service&&!c.services.includes(c.main_service))c.main_service='';
 if(!c.main_service){
  const candidates=[...new Set([...meta.catalog,...(meta.legacy_catalog||[])].filter(x=>c.class_ids.includes(x.id)).flatMap(x=>x.services||[]))].filter(code=>c.services.includes(code));
  if(candidates.length===1)c.main_service=candidates[0];
 }
}

export function chooseService(meta,card,code,checked){
 syncServices(meta,card);
 const choice=card.service_selection;
 choice.added=choice.added.filter(x=>x!==code);choice.removed=choice.removed.filter(x=>x!==code);
 (checked?choice.added:choice.removed).push(code);
 syncServices(meta,card);
}

export function serviceOrigin(meta,card,code){
 if(card.service_selection?.removed.includes(code))return 'Исключено преподавателем';
 if(card.service_selection?.added.includes(code))return 'Добавлено преподавателем';
 if(card.status==='approved')return card.content.services.includes(code)?'Утверждено преподавателем':'Не выбрана';
 return recommendServices(meta,card.content).services.includes(code)?'По классификатору':'Не выбрана';
}
