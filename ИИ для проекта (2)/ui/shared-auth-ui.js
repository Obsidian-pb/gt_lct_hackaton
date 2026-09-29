(()=>{
 'use strict';
 if(globalThis.TRAINER_SHARED_SERVER!==true)return;
 const user=globalThis.TRAINER_USER;
 async function logout(){
  try{await fetch('/api/v1/auth/logout',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:'{}'});}catch{}
  try{
   sessionStorage.removeItem('giik.admin.session.v1');sessionStorage.removeItem('practice:student:tab');
   localStorage.removeItem('giik.teacher.profile.v1');localStorage.removeItem('giik.student.profile.v1');localStorage.removeItem('practice:student');
   const admin=JSON.parse(localStorage.getItem('giik.admin.account.v1')||'null');if(admin?.server_managed)localStorage.removeItem('giik.admin.account.v1');
  }catch{}
  location.assign('/');
 }
 document.addEventListener('click',event=>{
  const button=event.target?.closest?.('#teacher-close,#student-exit,.admin-exit');
  if(!button)return;
  event.preventDefault();event.stopImmediatePropagation();void logout();
 },true);
 function enforceIdentity(){
  if(!user)return;
  if(user.role==='student'){
   const profile=document.querySelector('#student-profile-name');if(profile){profile.value=user.name;profile.disabled=true;}
   const lobby=document.querySelector('input[aria-label="Имя участника"]');if(lobby){lobby.value=user.name;lobby.disabled=true;}
  }
  if(user.role==='teacher'){
   const profile=document.querySelector('#profile-input');if(profile){profile.value=user.name;profile.disabled=true;}
  }
 }
 enforceIdentity();new MutationObserver(enforceIdentity).observe(document.documentElement,{childList:true,subtree:true});
})();
