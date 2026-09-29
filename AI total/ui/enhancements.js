(()=>{
 let busy=false;
 const enhance=()=>{if(busy)return;busy=true;queueMicrotask(()=>{busy=false;for(const cascade of document.querySelectorAll('.classification-cascade')){
   const rows=[...cascade.querySelectorAll('.cascade-row')];if(!rows.length)continue;
   const complete=rows.every(row=>{const b=row.querySelector('.cascade-choices button.selected');return b&&b.textContent.trim()!=='Любой';});if(!complete)continue;
   const select=cascade.querySelector('.leaf-select select');if(!select||select.value||select.options.length!==2)continue;
   select.value=select.options[1].value;select.dispatchEvent(new Event('change',{bubbles:true}));
   setTimeout(()=>{const details=cascade.closest('details');if(!details)return;const add=[...details.querySelectorAll('button')].find(b=>b.textContent.trim()==='Добавить выбранный тип'&&!b.disabled);if(add)add.click();},0);
  }});};
 new MutationObserver(enhance).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['class','value']});document.addEventListener('click',()=>setTimeout(enhance,0));document.addEventListener('change',()=>setTimeout(enhance,0));enhance();
})();
