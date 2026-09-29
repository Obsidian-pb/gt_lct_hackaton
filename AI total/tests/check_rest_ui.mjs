// Run with Playwright installed. Optional AI_TEST_BROWSER_PATH selects a local Chromium binary.
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.AI_TEST_PLAYWRIGHT||'playwright');
const server=spawn(process.env.AI_TEST_PYTHON||'python',['-u','-c',"exec(open('tests/ui_fixture.py',encoding='utf-8').read())"],{env:{...process.env,PYTHONUTF8:'1',AI_TEST_REST_ONLY:'1'}});
let out='',err='';server.stdout.on('data',b=>out+=b);server.stderr.on('data',b=>err+=b);
const launch={headless:true};
if(process.env.AI_TEST_BROWSER_PATH)Object.assign(launch,{executablePath:process.env.AI_TEST_BROWSER_PATH,args:['--no-sandbox','--disable-dev-shm-usage']});
let browser;
try{
 browser=await chromium.launch(launch);
 for(let i=0;i<100&&!out.includes('http://');i++)await new Promise(r=>setTimeout(r,50));
 const base=out.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];assert.ok(base,err);
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[],rpc=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 page.on('request',r=>{const path=new URL(r.url()).pathname;if(path==='/api')rpc.push(r.url());if(path.startsWith('/api/v1/'))requests.push([r.method(),path]);});
 await page.goto(base+'/cards');await page.waitForFunction(()=>document.body.dataset.ready==='true');
 await page.locator('#category').selectOption('1');await page.locator('#generate').click();
 await page.waitForFunction(()=>!document.querySelector('#generate').disabled);
 const cards=await page.evaluate(()=>JSON.parse(localStorage.getItem('giik.card-workshop.v1')).cards);
 assert.equal(cards.length,1);
 assert.ok(requests.some(([m,p])=>m==='POST'&&p==='/api/v1/cards/generations'));
 await page.locator('#open-reference').click();await page.locator('#generate-reference').click();
 await page.waitForFunction(()=>!document.querySelector('#generate').disabled);
 assert.ok(requests.some(([m,p])=>m==='POST'&&p==='/api/v1/cards/reference-previews'));
 // Address data also goes through REST, with the original coordinates preserved.
 const geo=await page.evaluate(()=>globalThis.TrainingAPI.api('geo_addresses'));
 assert.ok(geo.addresses.some(x=>x.street==='улица Королёва'&&x.house==='7А'));
 const task=await page.evaluate(()=>globalThis.TrainingAPI.api('create',{sample:true,level:'medium',workflow:'caller'}));
 await page.evaluate(id=>globalThis.TrainingAPI.api('approve',{id,teacher:'Тестовый преподаватель'}),task.id);
 await page.goto(base+'/teacher');await page.waitForFunction(()=>!!globalThis.TrainingAPI);
 await page.evaluate(()=>globalThis.TrainingAPI.api('teacher_dashboard'));
 await page.goto(base+'/student');await page.waitForFunction(()=>document.body.dataset.studentReady==='true');
 await page.goto(base+'/scenarios');await page.waitForFunction(()=>!!globalThis.TrainingAPI);
 const dashboard=await page.evaluate(()=>globalThis.TrainingAPI.api('teacher_dashboard'));
 assert.ok(dashboard.tasks.some(t=>t.id===task.id));
 await page.goto(base+'/training');await page.waitForFunction(()=>!!globalThis.TrainingAPI);
 assert.ok((await page.evaluate(()=>globalThis.TrainingAPI.api('home'))).count>=1);
 await page.goto(base+'/api/docs');await page.locator('#routes tr').first().waitFor();
 assert.ok(await page.locator('#routes tr').count()>=40);
 assert.deepEqual(rpc,[]);assert.deepEqual(errors,[]);
 console.log(JSON.stringify({result:'passed',restRequests:requests.length,legacyRpcRequests:rpc.length,pages:['cards','teacher','student','scenarios','training','api/docs']}));
}finally{await browser?.close();server.kill();}
