// Local OSM search: never send keystrokes to the public Nominatim API.
export const ADDRESS_KEYS=['country','region','city','district','area','object','street','house','block','building','apartment','entrance','floor','intercom','address_text','access'];
export const LOCATION_KEYS=['country','region','city','street','house','block','building'];
export function normalizeAddress(value){return String(value).toLowerCase().replace(/ё/g,'е').replace(/[^a-zа-я0-9/]+/g,' ').trim();}
const words=(value,context={})=>normalizeAddress(value).split(' ').filter(x=>x&&!['россия','красноярский','край','железногорск','г','город','улица','ул','дом','д','проспект','пр','переулок','пер',...normalizeAddress(context.city||'').split(' '),...normalizeAddress(context.region||'').split(' ')].includes(x));
function distance(a,b){let prev=Array.from({length:b.length+1},(_,i)=>i);for(let i=1;i<=a.length;i++){const row=[i];for(let j=1;j<=b.length;j++)row[j]=Math.min(row[j-1]+1,prev[j]+1,prev[j-1]+(a[i-1]===b[j-1]?0:1));prev=row;}return prev[b.length];}
export function searchAddresses(records,query,limit=12,context={}){
 const tokens=words(query,context);if(!tokens.length||normalizeAddress(query).length<2)return [];
 return records.map(record=>{
  const target=words(record.street+' '+record.house);let score=record.kind==='street'?0:3;
  const available=[...target];
  for(const token of tokens){let best=Infinity,index=-1;
   available.forEach((word,i)=>{const numeric=/\d/.test(token)||/\d/.test(word);const cost=word===token?0:word.startsWith(token)?(numeric?2:1):!numeric&&token.length>=4&&distance(token,word)<= (token.length>=8?2:1)?5:Infinity;if(cost<best){best=cost;index=i;}});
   if(index<0)return null;score+=best;available.splice(index,1);
  }
  return {record,score};
 }).filter(Boolean).sort((a,b)=>a.score-b.score||a.record.street.localeCompare(b.record.street,'ru')||a.record.house.localeCompare(b.record.house,'ru',{numeric:true})).slice(0,limit).map(x=>x.record);
}
export function addressFields(record,context={}){return {country:context.country||'Россия',region:context.region||'Красноярский край',city:context.city||'Железногорск',street:record.street,house:record.house,latitude:record.kind==='building'?String(record.point[1]):'',longitude:record.kind==='building'?String(record.point[0]):''};}
export function coordinates(fields){const lat=String(fields.latitude||'').trim(),lon=String(fields.longitude||'').trim();if(!lat||!lon)return null;const point=[Number(lon),Number(lat)];return point.every(Number.isFinite)&&Math.abs(point[0])<=180&&Math.abs(point[1])<=90?point:null;}
