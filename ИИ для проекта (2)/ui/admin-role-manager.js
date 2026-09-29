/* Admin classroom-role manager. Works with the bundled UI even when React sources were not rebuilt. */
(() => {
  'use strict';
  if (location.pathname !== '/admin' && location.pathname !== '/admin/') return;

  const ROLE_LABELS = {
    waiting: 'Роль не назначена',
    operator: 'Оператор 112',
    dds: 'Диспетчер 112',
    service: 'Диспетчер службы'
  };
  const STATUS_LABELS = {prepared:'Подготовлена',active:'Активна',completed:'Завершена'};
  let overlay = null;

  const waitForApi = async () => {
    for (let i=0;i<100;i++) {
      if (globalThis.TrainingAPI?.api) return globalThis.TrainingAPI.api;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error('REST API интерфейса не загрузился. Обновите страницу.');
  };

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  function ensureStyle(){
    if(document.getElementById('admin-role-manager-style')) return;
    const style=document.createElement('style');style.id='admin-role-manager-style';style.textContent=`
      #admin-role-manager-launcher{width:100%;height:50px;border:0;border-left:4px solid transparent;background:transparent;color:#536d80;display:flex;align-items:center;gap:14px;padding:0 20px;text-align:left;cursor:pointer;font-size:13px}
      #admin-role-manager-launcher:hover{background:#e8f1f7}#admin-role-manager-launcher i{font-style:normal;width:22px;text-align:center;font-size:22px;color:#4c6f88}
      .arm-overlay{position:fixed;inset:0;background:#25445d77;z-index:120;display:flex;justify-content:flex-end}.arm-panel{height:100vh;width:min(900px,88vw);background:#fff;overflow:auto;box-shadow:-12px 0 34px #1532482e;color:#334d63}
      .arm-head{position:sticky;top:0;z-index:2;background:#fff;border-bottom:1px solid #d7e0e7;padding:18px 22px;display:flex;align-items:center;justify-content:space-between;gap:10px}.arm-head h2{margin:0;font-size:21px}.arm-head button{border:0;background:transparent;font-size:30px;cursor:pointer;color:#42576a}
      .arm-tools{display:flex;gap:8px;flex-wrap:wrap;padding:14px 22px;background:#f7fafc;border-bottom:1px solid #e1e8ed}.arm-tools input{flex:1;min-width:220px;height:38px;border:1px solid #cfdbe3;padding:0 10px}.arm-tools button{height:38px;border:1px solid #bcd0de;background:#fff;color:#3774a4;padding:0 13px;cursor:pointer}.arm-note{margin:12px 22px;padding:10px;background:#eef7ff;border-left:3px solid #2587e9;font-size:12px}.arm-error{background:#fff0f1;border-left-color:#d94b55;color:#a5333c}
      .arm-training{margin:14px 22px;border:1px solid #d7e0e7}.arm-training>header{padding:12px 14px;background:#edf4f8;display:flex;justify-content:space-between;gap:12px}.arm-training>header strong{font-size:14px}.arm-training>header small{display:block;color:#78909f;margin-top:4px}.arm-row{display:grid;grid-template-columns:minmax(180px,1.3fr) minmax(170px,1fr) minmax(210px,1.2fr);gap:10px;padding:12px 14px;border-top:1px solid #e6ecef;align-items:end}.arm-person strong{display:block;font-size:12px}.arm-person small{display:block;color:#80929e;margin-top:4px}.arm-row label{font-size:10px;color:#657c8c;display:flex;flex-direction:column;gap:5px}.arm-row select{height:36px;border:1px solid #cbd8df;background:#fff;padding:0 8px}.arm-row select:disabled{background:#f0f3f5;color:#8a99a3}.arm-add-self{background:#eff8ff}.arm-add-self button{height:36px;border:0;background:#168cce;color:#fff;padding:0 14px;font-weight:700;cursor:pointer}.arm-add-self button:disabled{opacity:.6;cursor:default}.arm-empty{padding:28px;text-align:center;color:#80919c}.arm-self{background:#f1fbf7}.arm-badge{display:inline-block;padding:3px 7px;border-radius:10px;background:#dff5eb;color:#237557;font-size:9px;margin-left:7px}
      @media(max-width:760px){.arm-row{grid-template-columns:1fr}.arm-panel{width:96vw}}
    `;document.head.appendChild(style);
  }

  function adminName(){
    try{return JSON.parse(localStorage.getItem('giik.admin.account.v1')||'null')?.name||'';}catch{return '';}
  }

  async function assign(training, participant, role, service=''){
    const api=await waitForApi();
    const services=await api('services_list');
    const nextService=role==='service' ? (service || participant.service || Object.keys(services)[0] || '') : '';
    if(role==='service'&&!nextService) throw new Error('Нет доступных служб для роли диспетчера службы.');
    await api('training_role', {resource_id:training.id, participant_id:participant.id, teacher:training.teacher, role, service:nextService});
  }

  async function addSelf(training, role, service=''){
    const api=await waitForApi(),name=adminName();
    if(!name) throw new Error('Не удалось определить имя администратора. Войдите в админку заново.');
    const services=await api('services_list');
    const nextService=role==='service' ? (service || Object.keys(services)[0] || '') : '';
    if(role==='service'&&!nextService) throw new Error('Нет доступных служб для роли диспетчера службы.');
    const lobby=await api('training_add_participants',{resource_id:training.id,teacher:training.teacher,students:[name]});
    const participant=(lobby.participants||[]).find(p=>p.student.trim().toLocaleLowerCase('ru')===name.trim().toLocaleLowerCase('ru'));
    if(!participant) throw new Error('Сервер добавил участника, но не вернул его в составе тренировки.');
    await api('training_role',{resource_id:training.id,participant_id:participant.id,teacher:training.teacher,role,service:nextService});
  }

  async function render(filter=''){
    if(!overlay) return;
    const body=overlay.querySelector('.arm-body'),notice=overlay.querySelector('.arm-note');
    body.innerHTML='<div class="arm-empty">Загружаю тренировки…</div>';
    try{
      const api=await waitForApi();
      const [trainings,services]=await Promise.all([api('training_list'),api('services_list')]);
      const q=filter.trim().toLocaleLowerCase('ru'),me=adminName().toLocaleLowerCase('ru');
      const rows=trainings.filter(t=>!q || t.title.toLocaleLowerCase('ru').includes(q) || (t.participants||[]).some(p=>p.student.toLocaleLowerCase('ru').includes(q)));
      notice.className='arm-note';
      notice.textContent='Системная роль «Администратор» не меняется. Если вас ещё нет среди участников, нажмите «Добавить себя». После добавления можно работать оператором, диспетчером 112 или диспетчером службы.';
      if(!rows.length){body.innerHTML='<div class="arm-empty">Тренировки или участники по фильтру не найдены.</div>';return;}
      body.innerHTML=rows.map(t=>{const participants=t.participants||[],hasSelf=!!me&&participants.some(p=>p.student.trim().toLocaleLowerCase('ru')===me);const addSelfRow=!hasSelf&&t.status==='prepared'?`<div class="arm-row arm-add-self" data-add-self><div class="arm-person"><strong>${esc(adminName())}<span class="arm-badge">это вы</span></strong><small>Вы ещё не участник этой тренировки</small></div><label>Добавить себя как<select data-add-role>${Object.entries(ROLE_LABELS).filter(([v])=>v!=='waiting').map(([v,l])=>`<option value="${v}" ${v==='dds'?'selected':''}>${esc(l)}</option>`).join('')}</select></label><div><button type="button" data-add-button>Добавить себя</button></div></div>`:'';return `<section class="arm-training" data-training="${esc(t.id)}"><header><div><strong>${esc(t.title)}</strong><small>${esc(t.group||'Без группы')} · ${esc(STATUS_LABELS[t.status]||t.status)}</small></div><small>${participants.length} участников</small></header>${addSelfRow}${participants.length?participants.map(p=>{
        const isSelf=me && p.student.trim().toLocaleLowerCase('ru')===me;
        return `<div class="arm-row ${isSelf?'arm-self':''}" data-participant="${esc(p.id)}"><div class="arm-person"><strong>${esc(p.student)}${isSelf?'<span class="arm-badge">это вы</span>':''}</strong><small>Текущая роль: ${esc(ROLE_LABELS[p.role]||p.role)}</small></div><label>Учебная роль<select data-role ${t.status!=='prepared'?'disabled':''}>${Object.entries(ROLE_LABELS).map(([v,l])=>`<option value="${v}" ${p.role===v?'selected':''}>${esc(l)}</option>`).join('')}</select></label><label data-service-wrap style="${p.role==='service'?'':'visibility:hidden'}">Служба<select data-service ${t.status!=='prepared'?'disabled':''}><option value="">Выберите службу</option>${Object.entries(services).map(([c,l])=>`<option value="${esc(c)}" ${p.service===c?'selected':''}>${esc(c)} · ${esc(l)}</option>`).join('')}</select></label></div>`;
      }).join(''):'<div class="arm-empty">Участников пока нет.</div>'}</section>`}).join('');

      body.querySelectorAll('[data-add-self]').forEach(row=>{const section=row.closest('.arm-training'),training=trainings.find(t=>t.id===section.dataset.training),role=row.querySelector('[data-add-role]'),button=row.querySelector('[data-add-button]');button?.addEventListener('click',async()=>{button.disabled=true;role.disabled=true;try{await addSelf(training,role.value);notice.className='arm-note';notice.textContent=`Вы добавлены в «${training.title}» как «${ROLE_LABELS[role.value]}». Системная роль администратора сохранена.`;await render(overlay.querySelector('[data-filter]').value);}catch(e){notice.className='arm-note arm-error';notice.textContent=e.message;button.disabled=false;role.disabled=false;}});});
      body.querySelectorAll('.arm-row[data-participant]').forEach(row=>{
        const section=row.closest('.arm-training'),training=trainings.find(t=>t.id===section.dataset.training),participant=training.participants.find(p=>p.id===row.dataset.participant),role=row.querySelector('[data-role]'),service=row.querySelector('[data-service]'),wrap=row.querySelector('[data-service-wrap]');
        role?.addEventListener('change',async()=>{
          const old=participant.role; role.disabled=true;if(service)service.disabled=true;
          try{await assign(training,participant,role.value,service?.value||'');notice.className='arm-note';notice.textContent=`Роль ${participant.student} изменена на «${ROLE_LABELS[role.value]}».`;await render(overlay.querySelector('[data-filter]').value);}catch(e){role.value=old;notice.className='arm-note arm-error';notice.textContent=e.message;role.disabled=false;if(service)service.disabled=false;}
        });
        service?.addEventListener('change',async()=>{service.disabled=true;role.disabled=true;try{await assign(training,participant,'service',service.value);notice.className='arm-note';notice.textContent=`Служба для ${participant.student} изменена.`;await render(overlay.querySelector('[data-filter]').value);}catch(e){notice.className='arm-note arm-error';notice.textContent=e.message;role.disabled=false;service.disabled=false;}});
      });
    }catch(e){body.innerHTML='<div class="arm-empty">Не удалось загрузить учебные роли.</div>';notice.className='arm-note arm-error';notice.textContent=e.message;}
  }

  function open(){
    ensureStyle();
    overlay=document.createElement('div');overlay.className='arm-overlay';overlay.innerHTML=`<aside class="arm-panel" role="dialog" aria-modal="true" aria-label="Учебные роли"><div class="arm-head"><div><small>АДМИНИСТРАТОР</small><h2>Учебные роли участников</h2></div><button type="button" aria-label="Закрыть">×</button></div><div class="arm-tools"><input data-filter placeholder="Найти тренировку или участника"><button data-me>Показать меня</button><button data-refresh>Обновить</button></div><p class="arm-note">Загрузка…</p><div class="arm-body"></div></aside>`;
    document.body.appendChild(overlay);
    overlay.addEventListener('mousedown',e=>{if(e.target===overlay)close();});
    overlay.querySelector('.arm-head button').onclick=close;
    const input=overlay.querySelector('[data-filter]');let timer;input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>render(input.value),180);});
    overlay.querySelector('[data-refresh]').onclick=()=>render(input.value);
    overlay.querySelector('[data-me]').onclick=()=>{input.value=adminName();render(input.value);};
    render('');
  }
  function close(){overlay?.remove();overlay=null;}

  async function install(){
    // Keep this launcher even when the React admin contains an embedded editor: it also
    // lets the administrator enroll their own linked learner profile in a prepared session.
    ensureStyle();
    for(let i=0;i<100;i++){
      const nav=document.querySelector('.admin-sidebar nav');
      if(nav){
        if(document.getElementById('admin-role-manager-launcher'))return;
        const button=document.createElement('button');button.id='admin-role-manager-launcher';button.type='button';button.innerHTML='<i>⇄</i><span>Учебные роли</span>';button.addEventListener('click',open);nav.appendChild(button);return;
      }
      await new Promise(resolve=>setTimeout(resolve,100));
    }
  }
  install();
})();
