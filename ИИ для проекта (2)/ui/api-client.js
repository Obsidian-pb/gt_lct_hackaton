/* Shared REST client for React and the existing prototype/scenario pages. */
(() => {
 'use strict';
 let configuration = {};
 const meta = name => globalThis.document?.querySelector(`meta[name="${name}"]`)?.content;
 class APIError extends Error {
  constructor(message, {status=0,code='network_error',requestId='',details}={}) {
   super(message);this.name='APIError';this.status=status;this.code=code;this.requestId=requestId;this.details=details;
  }
 }
 function configure({baseUrl,token}={}) {
  configuration={baseUrl,token};
 }
 async function request(method,path,payload={},options={}) {
  const base=(configuration.baseUrl||globalThis.TRAINING_API_BASE||meta('api-base')||'/api/v1').replace(/\/$/,'');
  if(!path.startsWith('/')||path.startsWith('//'))throw new APIError('Укажите относительный путь ресурса REST API.');
  let url=base+path;
  const headers={'Accept':'application/json'};
  const bearer=configuration.token||globalThis.TRAINING_API_TOKEN;
  if(bearer)headers.Authorization='Bearer '+bearer;
  else if(meta('ui-token'))headers['X-UI-Token']=meta('ui-token');
  if(method==='GET') {
   const query=new URLSearchParams();
   for(const [key,value] of Object.entries(payload))if(value!==undefined&&value!==null)query.set(key,String(value));
   if(query.size)url+='?'+query;
  } else headers['Content-Type']='application/json';
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),options.timeout||110000);
  try {
   const response=await fetch(url,{method,headers,cache:'no-store',credentials:'same-origin',
    ...(method==='GET'?{}:{body:JSON.stringify(payload)}),signal:controller.signal});
   let body;
   try{body=await response.json();}catch{throw new APIError('Сервер вернул некорректный ответ.',{status:response.status,code:'invalid_response'});}
   if(!response.ok||body.error)throw new APIError(body.error?.message||'Не удалось выполнить запрос.',{
    status:response.status,code:body.error?.code||'http_error',requestId:body.request_id||response.headers.get('X-Request-ID')||'',details:body.error?.details});
   if(!Object.prototype.hasOwnProperty.call(body,'data'))throw new APIError('В ответе API отсутствует поле data.',{code:'invalid_response'});
   return body.data;
  } catch(error) {
   if(error.name==='AbortError')throw new APIError('Время ожидания истекло. Сервер мог завершить операцию: обновите состояние перед повторной отправкой.',{code:'timeout'});
   if(error instanceof TypeError)throw new APIError('Нет соединения с API. Проверьте адрес сервера и его запуск.',{code:'network_error'});
   throw error;
  } finally {clearTimeout(timer);}
 }
 async function api(action,payload={}) {
  const key=action==='student_action'?action+'_'+payload.operation:action;
  const route=globalThis.TrainingAPIRoutes?.[key];
  if(!route)throw new APIError('Неизвестная операция интерфейса.',{code:'unknown_operation'});
  const data={...payload};delete data.operation;
  let path=route.path;
  for(const name of route.parameters) {
   if(data[name]===undefined||data[name]===null)throw new APIError('Не задан параметр '+name,{code:'missing_parameter'});
   path=path.replace('{'+name+'}',encodeURIComponent(data[name]));delete data[name];
  }
  return request(route.method,path,data,{timeout:action==='card_reference'?240000:110000});
 }
 globalThis.TrainingAPI=Object.freeze({api,request,configure,APIError});
})();
