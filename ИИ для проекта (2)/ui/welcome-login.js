(()=>{
 'use strict';
 if(location.pathname!=='/'&&location.pathname!=='')return;
 let loginValue='';
 let passwordValue='';
 let busy=false;
 const roleFromPage=()=>{
  const pressed=document.querySelector('.welcome-roles button[aria-pressed="true"]');
  if(!pressed)return 'teacher';
  if(pressed.id==='role-student'||pressed.dataset.role==='student')return 'student';
  if(pressed.id==='role-admin'||pressed.dataset.role==='admin')return 'admin';
  return 'teacher';
 };
 const homeFor=role=>role==='admin'?'/admin':role==='student'?'/student':'/teacher';
 function setError(message){
  const box=document.querySelector('[data-welcome-auth-error]');
  if(!box)return;
  box.textContent=message||'';
  box.hidden=!message;
 }
 function setBusy(value){
  busy=value;
  const button=document.querySelector('.welcome-enter');
  if(!button)return;
  button.setAttribute('aria-busy',String(value));
  button.style.pointerEvents=value?'none':'';
  button.style.opacity=value?'.65':'';
  const text=button.firstChild;
  if(text&&text.nodeType===Node.TEXT_NODE)text.textContent=value?'Входим… ':'Войти ';
 }
 function ensureFields(){
  const welcome=document.querySelector('.welcome');
  const roles=welcome?.querySelector('.welcome-roles');
  const enter=welcome?.querySelector('.welcome-enter');
  if(!welcome||!roles||!enter)return;
  let fields=welcome.querySelector('[data-server-login-fields]');
  if(!fields){
   fields=document.createElement('div');
   fields.className='welcome-auth-fields';
   fields.dataset.serverLoginFields='1';
   fields.innerHTML=`
    <label class="welcome-auth-field"><span>Логин</span><input id="welcome-login" name="username" autocomplete="username" maxlength="64" placeholder="Введите логин" required></label>
    <label class="welcome-auth-field"><span>Пароль</span><input id="welcome-password" name="password" type="password" autocomplete="current-password" maxlength="4096" placeholder="Введите пароль" required></label>
    <p class="welcome-auth-error" data-welcome-auth-error role="alert" hidden></p>`;
   enter.before(fields);
  }
  const login=fields.querySelector('#welcome-login');
  const password=fields.querySelector('#welcome-password');
  if(login&&login.value!==loginValue)login.value=loginValue;
  if(password&&password.value!==passwordValue)password.value=passwordValue;
 }
 async function submit(){
  if(busy)return;
  ensureFields();
  const login=document.querySelector('#welcome-login');
  const password=document.querySelector('#welcome-password');
  loginValue=(login?.value||'').trim();
  passwordValue=password?.value||'';
  if(!loginValue||!passwordValue){
   setError('Введите логин и пароль.');
   (loginValue?password:login)?.focus();
   return;
  }
  setBusy(true);setError('');
  const role=roleFromPage();
  try{
   const response=await fetch('/api/v1/auth/login',{
    method:'POST',credentials:'same-origin',cache:'no-store',
    headers:{'Content-Type':'application/json','Accept':'application/json'},
    body:JSON.stringify({login:loginValue,password:passwordValue,role})
   });
   let body={};try{body=await response.json();}catch{}
   if(!response.ok){
    if(response.status===404||response.status===405)throw new Error('Серверная авторизация не запущена. Запустите START_SHARED_SERVER.cmd.');
    throw new Error(body?.error?.message||'Неверный логин или пароль.');
   }
   location.assign(body?.data?.home||homeFor(role));
  }catch(error){
   setError(error?.message||'Не удалось войти.');
   setBusy(false);
  }
 }
 document.addEventListener('input',event=>{
  if(event.target?.id==='welcome-login')loginValue=event.target.value;
  if(event.target?.id==='welcome-password')passwordValue=event.target.value;
 },true);
 document.addEventListener('keydown',event=>{
  if(event.key==='Enter'&&(event.target?.id==='welcome-login'||event.target?.id==='welcome-password')){
   event.preventDefault();void submit();
  }
 },true);
 document.addEventListener('click',event=>{
  const enter=event.target?.closest?.('.welcome-enter');
  if(enter&&location.pathname==='/'){
   event.preventDefault();event.stopImmediatePropagation();void submit();return;
  }
  if(event.target?.closest?.('.welcome-roles button')){setError('');queueMicrotask(ensureFields);}
 },true);
 ensureFields();
 new MutationObserver(ensureFields).observe(document.documentElement,{childList:true,subtree:true});
})();
