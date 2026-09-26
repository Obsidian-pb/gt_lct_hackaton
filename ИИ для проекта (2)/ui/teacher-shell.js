/* Shared visual shell for the teacher dashboard and existing card workshop. */
(()=>{
 const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const icons={
  plus:'<path d="M12 3v18M3 12h18"/>',
  file:'<path d="M6 2h8l5 5v15H6zM14 2v6h5"/>',
  users:'<circle cx="10" cy="7" r="4"/><path d="M2 22v-3a8 8 0 0 1 16 0v3M16 3a4 4 0 0 1 0 8M20 22v-4a9 9 0 0 0-3-6"/>',
  chart:'<path d="M3 21V13h4v8zM10 21V8h4v13zM17 21V2h4v19z"/>',
  exit:'<path d="M13 3H4v18h9M10 12h12M17 7l5 5-5 5"/>',
  arrow:'<path d="M2 12h25M20 6l7 6-7 6"/>'
 };
 const svg=(name)=>`<svg viewBox="0 0 ${name==='arrow'?30:24} 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">${icons[name]||icons.file}</svg>`;
 function profile(){try{return JSON.parse(localStorage.getItem('giik.teacher.profile.v1'))?.name||'Преподаватель';}catch{return 'Преподаватель';}}
 function current(){return location.pathname==='/cards'?'cards':location.hash.slice(1)||'home';}
 const links=[['home','Главная'],['trainings','Тренировки'],['scenarios','Сценарии'],['students','Обучающиеся'],['results','Результаты'],['cards','Карточки'],['messages','Сообщения']];
 const shell=document.getElementById('teacher-shell');
 shell.innerHTML=`<a class="teacher-skip" href="#${location.pathname==='/cards'?'workshop':'teacher-content'}">К содержимому</a><aside class="teacher-sidebar"><nav aria-label="Меню преподавателя">${links.map(([key,label])=>`<a data-section="${key}" href="${key==='cards'?'/cards':'/teacher#'+key}">${label}</a>`).join('')}</nav><a class="teacher-settings" data-section="settings" href="/teacher#settings">Настройки</a></aside>
 <header class="teacher-header"><button class="teacher-menu" aria-label="Открыть меню" aria-expanded="false">☰</button><div class="teacher-profile"><a href="/teacher#settings"><span id="profile-name">${escape(profile())}</span><small>Преподаватель</small></a><button id="teacher-exit" title="Завершить работу" aria-label="Завершить работу">${svg('exit')}</button></div></header>
 <dialog id="teacher-exit-dialog"><h2>Завершить работу?</h2><p>Сохранённые карточки останутся в этом браузере.</p><div class="teacher-dialog-actions"><button id="teacher-stay">Остаться</button><button id="teacher-close" class="teacher-dark">Завершить</button></div></dialog>
`;
 function update(){document.querySelectorAll('[data-section]').forEach(a=>{const active=a.dataset.section===current();if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});document.getElementById('profile-name').textContent=profile();}
 document.querySelector('.teacher-menu').addEventListener('click',()=>{const open=document.body.classList.toggle('teacher-menu-open');document.querySelector('.teacher-menu').setAttribute('aria-expanded',String(open));});
 document.querySelectorAll('[data-section]').forEach(a=>a.addEventListener('click',()=>{document.body.classList.remove('teacher-menu-open');document.querySelector('.teacher-menu').setAttribute('aria-expanded','false');}));
 const dialog=document.getElementById('teacher-exit-dialog');
 document.getElementById('teacher-exit').addEventListener('click',()=>{
  if(document.querySelector('#generate:disabled')||document.querySelector('#editor[inert]')){alert('Дождитесь текущей операции. Генерацию можно остановить после текущей карточки.');return;}
  dialog.showModal();
 });
 document.getElementById('teacher-stay').addEventListener('click',()=>dialog.close());
 document.getElementById('teacher-close').addEventListener('click',()=>{location.assign('/');});
 window.addEventListener('hashchange',update);window.addEventListener('storage',update);
 window.TeacherShell={svg,escape,profile,update};update();
})();
