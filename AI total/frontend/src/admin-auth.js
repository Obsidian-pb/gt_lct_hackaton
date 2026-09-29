/* Server-side admin auth (Этап 2.1): JWT issued by POST /api/v1/auth/login.
   Tokens live in sessionStorage; refresh rotation happens transparently. */
import {api} from './api.js';

export const ADMIN_ACCOUNT='giik.admin.account.v1';
export const ADMIN_SESSION='giik.admin.session.v1';
export const ADMIN_USERS='giik.admin.users.v1';

const SESSION_MAX_SKEW=30; // seconds before exp: try a silent refresh

function parseToken(token){
 try{
  const part=token.split('.')[1];
  if(!part)return null;
  const pad='='.repeat((4-part.length%4)%4);
  return JSON.parse(decodeURIComponent(escape(atob(part.replace(/-/g,'+').replace(/_/g,'/')+pad))));
 }catch{return null;}
}
function readSession(){
 try{return JSON.parse(sessionStorage.getItem(ADMIN_SESSION)||'null');}catch{return null;}
}
export function accessToken(){return readSession()?.access_token||'';}
export function refreshToken(){return readSession()?.refresh_token||'';}
export function authHeaders(){const t=accessToken();return t?{Authorization:'Bearer '+t}:{};}
function saveSession(session){sessionStorage.setItem(ADMIN_SESSION,JSON.stringify(session));}
function clearLegacy(){localStorage.removeItem(ADMIN_ACCOUNT);localStorage.removeItem(ADMIN_USERS);}

export function adminSignedIn(){
 const session=readSession();
 if(!session?.ok||!session.access_token)return false;
 const claims=parseToken(session.access_token);
 if(!claims?.exp)return false;
 // Expired: try one silent refresh with the stored refresh token.
 if(claims.exp*1000-Date.now()<=SESSION_MAX_SKEW*1000){
  refreshAuth().catch(()=>{});
  return false;
 }
 return true;
}
export function adminName(){
 const session=readSession();
 return session?.user?.full_name||session?.user?.login||'Администратор';
}
export async function signInAdmin(login,password){
 const data=await api('auth_login',{login,password});
 saveSession({ok:true,access_token:data.access_token,refresh_token:data.refresh_token,user:data.user,at:new Date().toISOString()});
 clearLegacy();
 return data.user;
}
export async function refreshAuth(){
 const token=refreshToken();
 if(!token)throw new Error('Нет refresh-токена.');
 const data=await api('auth_refresh',{refresh_token:token});
 saveSession({...readSession(),access_token:data.access_token,refresh_token:data.refresh_token,user:data.user,at:new Date().toISOString()});
 return data.user;
}
export async function adminLogout(){
 const token=refreshToken();
 // Clear the session synchronously so navigation cannot keep a stale login.
 sessionStorage.removeItem(ADMIN_SESSION);
 clearLegacy();
 try{if(token)await api('auth_logout',{refresh_token:token});}catch{}
}
