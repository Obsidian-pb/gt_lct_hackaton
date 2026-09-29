export async function serverLogout(){
 try{
  await fetch('/api/v1/auth/logout',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:'{}'});
 }catch{}
 try{sessionStorage.removeItem('giik.admin.session.v1');sessionStorage.removeItem('practice:student:tab');}catch{}
 if(globalThis.TRAINER_SHARED_SERVER){
  try{
   localStorage.removeItem('giik.teacher.profile.v1');
   localStorage.removeItem('giik.student.profile.v1');
   localStorage.removeItem('practice:student');
   const admin=JSON.parse(localStorage.getItem('giik.admin.account.v1')||'null');
   if(admin?.server_managed)localStorage.removeItem('giik.admin.account.v1');
  }catch{}
 }
}

export function serverIdentity(){return globalThis.TRAINER_USER||null;}
export function isSharedServer(){return globalThis.TRAINER_SHARED_SERVER===true;}
