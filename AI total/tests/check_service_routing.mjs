import assert from 'node:assert/strict';
import fs from 'node:fs';
import {recommendServices,syncServices,chooseService,syncLearnerServices} from '../frontend/src/service-routing.js';
const source=JSON.parse(fs.readFileSync(new URL('../catalog/classifier.json',import.meta.url),'utf8'));
const meta={catalog:source.entries,services:source.services};
const card=()=>({status:'draft',content:{class_ids:['1010101'],services:['101'],main_service:'101',flags:{}}});
const c=card();syncServices(meta,c);
assert.ok(c.content.services.includes('101'));
assert.ok(c.content.services.includes('ZODD'),'Unconditional routing column');
assert.ok(!c.content.services.includes('103'),'Unknown injuries do not imply injuries');
assert.ok(!c.content.services.includes('CULTURE'),'Unsupported condition is not guessed');
assert.ok(recommendServices(meta,c.content).pending.some(r=>r.service==='CULTURE'));
c.content.flags.injured='yes';syncServices(meta,c);
for(const code of ['102','103','ZEMP'])assert.ok(c.content.services.includes(code));
c.content.flags.not_on_scene='yes';syncServices(meta,c);
assert.ok(!c.content.services.includes('103'),'No response overrides injury branch for absent casualty');
chooseService(meta,c,'103',true);syncServices(meta,c);
assert.ok(c.content.services.includes('103'),'Explicit teacher addition overrides automatic routing');
chooseService(meta,c,'102',false);c.content.flags.gas='yes';syncServices(meta,c);
assert.ok(c.content.services.includes('104'));
assert.ok(!c.content.services.includes('102'),'Teacher exclusion survives recalc');
const restored=JSON.parse(JSON.stringify(c));syncServices(meta,restored);
assert.deepEqual(restored,c,'Local storage roundtrip preserves overrides');
c.content.class_ids=['17070500'];c.content.flags={};syncServices(meta,c);
assert.ok(!c.content.services.includes('104'),'Obsolete automatic service removed');
assert.ok(c.content.services.includes('103'),'Teacher addition survives class change');
assert.ok(!c.content.services.includes('102'));
c.status='approved';const frozen=JSON.stringify(c);syncServices(meta,c);assert.equal(JSON.stringify(c),frozen);
const old=card();old.content.services.push('VETERINARY');syncServices(meta,old);
assert.deepEqual(old.service_selection.added,['VETERINARY'],'Existing teacher additions preserved');
const multi=card();multi.content.class_ids.push('17070500');multi.content.flags={injured:'yes',not_on_scene:'yes'};
// A prohibition for one incident must not suppress an independent positive rule.
meta.catalog.push({id:'test-positive',services:['103'],rules:[]});multi.content.class_ids.push('test-positive');
syncServices(meta,multi);assert.ok(multi.content.services.includes('103'));

// Student card: classifier/flags recalculate the recommended services, while
// explicit learner changes survive the next automatic recalculation.
const learnerBase={fields:{},report:'',class_ids:[],services:[],main_service:'',flags:{}};
const learnerAuto=syncLearnerServices(meta,learnerBase,{...learnerBase,class_ids:['1010101'],services:[],flags:{}});
assert.ok(learnerAuto.services.includes('101'),'Learner receives automatic service composition');
const learnerManual={...learnerAuto,services:[...learnerAuto.services.filter(x=>x!=='ZODD'),'VETERINARY']};
const learnerRecalc=syncLearnerServices(meta,learnerManual,{...learnerManual,flags:{injured:'yes'}});
assert.ok(!learnerRecalc.services.includes('ZODD'),'Learner manual exclusion survives recalculation');
assert.ok(learnerRecalc.services.includes('VETERINARY'),'Learner manual addition survives recalculation');
assert.ok(learnerRecalc.services.includes('103'),'New classifier condition can still add an automatic service');

console.log('PASS: real classifier, conditional routing, teacher and learner overrides, type changes, migration and frozen approval.');
