(()=>{
 'use strict';
 if(!/^\/(student|training)\/?$/.test(location.pathname)) return;
 const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
 const studentName=()=>{
  try{
   return new URLSearchParams(location.search).get('name')||sessionStorage.getItem('practice:student:tab')||JSON.parse(localStorage.getItem('giik.student.profile.v1')||'null')?.name||localStorage.getItem('practice:student')||'';
  }catch{return ''}
 };
 async function api(method,path,body){
  const token=document.querySelector('meta[name="ui-token"]')?.content||'';
  const r=await fetch('/api/v1'+path,{method,cache:'no-store',credentials:'same-origin',headers:{'Accept':'application/json',...(token?{'X-UI-Token':token}:{}),...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
  let payload={};try{payload=await r.json()}catch{}
  if(!r.ok||payload.error) throw new Error(payload.error?.message||'Не удалось выполнить запрос.');
  return payload.data;
 }
 let mounting=false;
 async function mount(){
  const root=document.querySelector('.dispatcher-desk');
  if(!root||root.querySelector('.dispatcher-ai-generator')||mounting) return;
  const student=studentName().trim();
  if(!student||student==='Обучающийся') return;
  mounting=true;
  try{
   const desks=await api('GET','/training-desks/'+encodeURIComponent(student));
   const eligible=(desks||[]).filter(d=>d.role==='dds'&&d.status==='active');
   if(!eligible.length) return;
   const osm=await api('GET','/geo/addresses');
   const cityLabel=osm.city+', '+osm.region;
   const section=document.createElement('section');
   section.className='dispatcher-ai-generator';
   section.dataset.dispatcherAiOverlay='1';
   section.innerHTML=`<div class="dispatcher-section-head"><div><small>САМОСТОЯТЕЛЬНАЯ ПРАКТИКА</small><h5>Создать эталонные карточки через ИИ</h5></div><span>Без оператора</span></div><p>ИИ сформирует вымышленные карточки и сразу отправит их вам как Диспетчеру 112. Можно перезванивать заявителю, уточнять сведения и направлять службы.</p><div class="dispatcher-ai-generator-grid">${eligible.length>1?`<label>Тренировка<select data-ai-training>${eligible.map(d=>`<option value="${esc(d.id)}">${esc(d.title)}</option>`).join('')}</select></label>`:''}<label>Количество<select data-ai-count><option>1</option><option>2</option><option>3</option><option selected>4</option></select></label><label>Город OSM<select data-ai-location><option value="${esc(cityLabel)}">${esc(cityLabel)}</option></select></label><label class="wide">Пожелание к примерам<input data-ai-topic maxlength="1000" placeholder="Необязательно: например, вечер, сложные адреса, разные службы"></label><button type="button" class="dispatcher-primary" data-ai-create>Создать 4 ИИ-карточки</button></div><p class="dispatcher-ai-generator-ok" data-ai-notice hidden></p>`;
   const count=section.querySelector('[data-ai-count]'),button=section.querySelector('[data-ai-create]'),notice=section.querySelector('[data-ai-notice]');
   count.addEventListener('change',()=>button.textContent=`Создать ${count.value} ИИ-карточки`);
   button.addEventListener('click',async()=>{
    const id=section.querySelector('[data-ai-training]')?.value||eligible[0].id;
    const locationValue=section.querySelector('[data-ai-location]').value.trim();
    if(!locationValue){notice.hidden=false;notice.textContent='Укажите локацию.';return;}
    button.disabled=true;count.disabled=true;notice.hidden=false;notice.textContent='ИИ создаёт карточки. Обычно это занимает несколько секунд на каждую…';
    try{
     const result=await api('POST',`/trainings/${encodeURIComponent(id)}/dispatcher-examples`,{student,count:Number(count.value),location:locationValue,topic:section.querySelector('[data-ai-topic]').value.trim()});
     notice.textContent=result?.message||`Готово. Создано карточек: ${count.value}.`;
     // DispatcherDesk refreshes itself every five seconds. Keep the message visible until then.
     setTimeout(()=>{notice.textContent+=' Очередь обновляется автоматически.';},800);
    }catch(e){notice.textContent=e.message;notice.style.background='#fff0ef';notice.style.color='#a91520';}
    finally{button.disabled=false;count.disabled=false;}
   });
   const heading=root.querySelector('.dispatcher-heading');
   if(heading) heading.insertAdjacentElement('afterend',section); else root.prepend(section);
  }catch(e){/* The React page already shows its own API errors; retry on the next DOM change. */}
  finally{mounting=false;}
 }
 const observer=new MutationObserver(()=>mount());
 observer.observe(document.documentElement,{subtree:true,childList:true});
 window.addEventListener('load',mount);
 setInterval(mount,3000);
 mount();
})();
