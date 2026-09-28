// Deliberately fictional prefix; this demo does not query a telephone network.
export function simulatedCallerId(){
 const digits=String(crypto.getRandomValues(new Uint32Array(1))[0]%10000000).padStart(7,'0');
 return `+7 (000) ${digits.slice(0,3)}-${digits.slice(3,5)}-${digits.slice(5)}`;
}
export function ensureCallerId(card,force=false){
 if(card.status==='approved')return false;
 const current=card.content.fields.phone_aon.trim();
 if(!force&&current&&current!=='Не определён: вымышленная карточка')return false;
 card.content.fields.phone_aon=simulatedCallerId();
 card.telephony={...card.telephony,mode:'simulated'};
 return true;
}
export function prepareCaller(card){
 let phone=simulatedCallerId();
 if(phone===card.content.fields.phone_aon)phone=phone.slice(0,-1)+(Number(phone.at(-1))+1)%10;
 card.caller_scenario={version:1,phone_callback:phone};
 card.caller_dialogue={turns:[],callback_disclosed:false};
}
