export const ADMIN_ACCOUNT='giik.admin.account.v1';
export const ADMIN_SESSION='giik.admin.session.v1';
export const ADMIN_USERS='giik.admin.users.v1';

export async function hashPassword(value){
 const bytes=new TextEncoder().encode(value);
 const digest=await crypto.subtle.digest('SHA-256',bytes);
 return Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,'0')).join('');
}
export function readAdminAccount(){try{return JSON.parse(localStorage.getItem(ADMIN_ACCOUNT)||'null');}catch{return null;}}
export function adminSignedIn(){try{const session=JSON.parse(sessionStorage.getItem(ADMIN_SESSION)||'null'),account=readAdminAccount();return session?.ok===true&&!!account&&session.login===account.login;}catch{return false;}}
export function adminName(){return readAdminAccount()?.name||'Администратор';}
export function adminLogout(){sessionStorage.removeItem(ADMIN_SESSION);}
export async function createAdmin({name,login,password}){
 const account={version:1,name:name.trim(),login:login.trim(),password_hash:await hashPassword(password),created_at:new Date().toISOString()};
 localStorage.setItem(ADMIN_ACCOUNT,JSON.stringify(account));
 seedAdminUser(account);
 sessionStorage.setItem(ADMIN_SESSION,JSON.stringify({ok:true,login:account.login,at:new Date().toISOString()}));
 return account;
}
export async function signInAdmin(login,password){
 const account=readAdminAccount();
 if(!account)return false;
 const ok=account.login===login.trim()&&account.password_hash===await hashPassword(password);
 if(ok){sessionStorage.setItem(ADMIN_SESSION,JSON.stringify({ok:true,login:account.login,at:new Date().toISOString()}));seedAdminUser(account);}
 return ok;
}
export function seedAdminUser(account=readAdminAccount()){
 if(!account)return;
 let list=[];try{list=JSON.parse(localStorage.getItem(ADMIN_USERS)||'[]');}catch{}
 if(!Array.isArray(list))list=[];
 let idx=list.findIndex(x=>x.login===account.login&&x.role==='Администратор');
 if(idx<0){const adminRows=list.map((x,i)=>x?.role==='Администратор'?i:-1).filter(i=>i>=0);if(adminRows.length===1)idx=adminRows[0];}
 const row={id:idx>=0?list[idx].id:crypto.randomUUID(),name:account.name,login:account.login,role:'Администратор',status:'Активен',last_login:new Date().toISOString(),permissions:['users','trainings','scenarios','cards','results','monitoring','system','settings']};
 if(idx>=0)list[idx]={...list[idx],...row};else list.unshift(row);
 // The administrator may also take part in a classroom session. Keep that training
 // identity separate from the privileged system account so changing a training role
 // never removes administrator access.
 let learnerIdx=list.findIndex(x=>x?.role==='Обучающийся'&&x?.linked_admin_login===account.login);
 if(learnerIdx<0)learnerIdx=list.findIndex(x=>x?.role==='Обучающийся'&&x?.name?.trim().toLocaleLowerCase('ru')===account.name.trim().toLocaleLowerCase('ru'));
 const learner={id:learnerIdx>=0?list[learnerIdx].id:crypto.randomUUID(),name:account.name,login:account.login,role:'Обучающийся',status:'Активен',last_login:list[learnerIdx]?.last_login||'',linked_admin_login:account.login,training_profile:true};
 if(learnerIdx>=0)list[learnerIdx]={...list[learnerIdx],...learner};else list.push(learner);
 localStorage.setItem(ADMIN_USERS,JSON.stringify(list));
}
