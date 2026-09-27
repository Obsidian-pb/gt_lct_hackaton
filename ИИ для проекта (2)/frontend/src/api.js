export async function api(action,payload={}) {
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),action==='card_reference'?240000:110000);
 try {
  const response=await fetch('/api',{method:'POST',headers:{'Content-Type':'application/json','X-UI-Token':document.querySelector('meta[name=ui-token]').content},body:JSON.stringify({action,payload}),signal:controller.signal});
  let data;try{data=await response.json();}catch{throw Error('Сервер вернул некорректный ответ. Сохранённые карточки остаются в браузере.');}
  if(!response.ok||data.error)throw Error(data.error||'Не удалось выполнить запрос.');
  return data.result;
 }catch(e){if(e.name==='AbortError')throw Error('Время ожидания ИИ истекло. Можно продолжить с этой позиции.');throw e;}
 finally{clearTimeout(timer);}
}
