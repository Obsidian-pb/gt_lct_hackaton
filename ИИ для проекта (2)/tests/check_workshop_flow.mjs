import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createWorkshopStore} from '../frontend/src/workshop-store.js';

const server=spawn(process.env.AI_TEST_PYTHON||'python',['-u','-c',"exec(open('tests/ui_fixture.py',encoding='utf-8').read())"],
 {env:{...process.env,PYTHONUTF8:'1'}});
let output='',stderr='';server.stdout.on('data',b=>output+=b);server.stderr.on('data',b=>stderr+=b);
try{
 for(let i=0;i<100&&!output.includes('http://');i++)await new Promise(r=>setTimeout(r,50));
 const base=output.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];assert.ok(base,stderr);
 const html=await (await fetch(base+'/cards')).text();
 const token=html.match(/name="ui-token" content="([^"]+)"/)?.[1];assert.ok(token);
 globalThis.document={querySelector:()=>({content:token})};
 const saved=new Map();globalThis.localStorage={getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)};
 globalThis.window={addEventListener(){},removeEventListener(){}};
 globalThis.TrainingAPI.configure({baseUrl:base+'/api/v1'});
 const store=createWorkshopStore();await store.init();assert.equal(store.getSnapshot().ready,true);
 store.addManual();let card=store.getSnapshot().state.cards[0];
 store.edit('content','title','Учебный пожар');
 store.edit('content','report','Я вижу дым в гараже на улице Лесной, дом 14. Мужчина заходил внутрь, я не видела, чтобы он вышел.');
 store.edit('field','description','Возможно, пожар в гараже.');
 store.edit('field','address_text','Учебный город, улица Лесная, дом 14');
 store.replaceClass(null,store.getSnapshot().meta.catalog.find(c=>c.category==='1'&&c.services.length)?.id);
 store.edit('teacher',null,'Глеб');
 await store.generateReference();card=store.getSnapshot().state.cards[0];
 assert.ok(card.reference,store.getSnapshot().notice);
 store.edit('reference_checked',null,true);assert.equal(card.reference_checked,true);
 await store.review('approve');
 assert.equal(card.status,'approved',store.getSnapshot().reviewFeedback);
 assert.ok(card.training_task_id,store.getSnapshot().reviewFeedback);
 assert.match(store.getSnapshot().reviewFeedback,/утверждены/);
 console.log('PASS: workshop form data -> reference -> teacher approval -> training publication.');
}finally{server.kill();}
