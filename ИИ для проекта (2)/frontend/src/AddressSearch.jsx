import {useEffect,useId,useMemo,useState} from 'react';
import {coordinates,searchAddresses} from './address-search.js';
import AddressMap from './AddressMap.jsx';
let cached;
function load(){if(!cached)cached=Promise.all(['/geo/addresses.json','/geo/map.json'].map(async url=>{const r=await fetch(url);if(!r.ok)throw Error('Не удалось загрузить карту и адреса.');return r.json();})).then(([index,map])=>({index,map})).catch(e=>{cached=null;throw e;});return cached;}
export default function AddressSearch({fields,geocoding,readonly,onSelect,onClear}){
 const [data,setData]=useState(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),[query,setQuery]=useState(''),[open,setOpen]=useState(false),[active,setActive]=useState(-1);
 const id=useId(),label=[fields.city,fields.street,fields.house].filter(Boolean).join(', ');
 useEffect(()=>{let alive=true;load().then(value=>{if(alive){setData(value);setError('');}}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[attempt]);
 useEffect(()=>{setQuery(label);setOpen(false);setActive(-1);},[label,readonly]);
 const results=useMemo(()=>data?searchAddresses(data.index.addresses,query):[],[data,query]);
 const point=coordinates(fields)||(geocoding?.kind==='street'?geocoding.point:null),kind=coordinates(fields)?'building':'street';
 const choose=record=>{onSelect(record);setQuery(['Железногорск',record.street,record.house].filter(Boolean).join(', '));setOpen(false);setActive(-1);};
 return <div className="address-lookup">
  <label htmlFor={id}>Поиск адреса · Железногорск, Красноярский край</label>
  <div className="address-search-row"><input id={id} type="search" role="combobox" aria-autocomplete="list" aria-expanded={open&&!readonly} aria-controls={id+'-results'} aria-activedescendant={open&&active>=0?id+'-option-'+active:undefined} autoComplete="off" placeholder="Начните вводить улицу и номер дома" disabled={readonly} value={query}
   onFocus={()=>setOpen(true)} onBlur={()=>setOpen(false)} onChange={e=>{setQuery(e.target.value);setOpen(true);setActive(-1);}}
   onKeyDown={e=>{if(e.key==='Escape'){setOpen(false);setActive(-1);}else if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();setOpen(true);setActive(i=>results.length?(i+(e.key==='ArrowDown'?1:-1)+results.length)%results.length:-1);}else if(e.key==='Enter'&&open&&active>=0&&results[active]){e.preventDefault();choose(results[active]);}}}/>
   <button type="button" disabled={readonly} onClick={()=>{onClear();setQuery('');setOpen(false);}} aria-label="Очистить адрес">×</button>
  </div>
  {open&&!readonly&&<div id={id+'-results'} className="address-suggestions" role="listbox" aria-label="Адреса OpenStreetMap">
   {results.map((record,i)=><button type="button" role="option" aria-selected={active===i} id={id+'-option-'+i} key={record.id} onPointerDown={e=>e.preventDefault()} onClick={()=>choose(record)}><span>{record.street}{record.house?', '+record.house:''}<small>Железногорск · {record.kind==='building'?'здание':'улица, уточните дом'}</small></span><small>OSM</small></button>)}
   {!results.length&&<p role="status">{!data?'Загружаем адреса…':query.trim().length<2?'Введите хотя бы две буквы улицы.':'Адрес не найден в местной копии OSM. Уточните написание или заполните поля вручную.'}</p>}
  </div>}
  {error?<p className="address-error" role="alert">{error} Поля можно заполнить вручную. <button type="button" onClick={()=>setAttempt(x=>x+1)}>Повторить загрузку</button></p>:!data?<p role="status">Загружаем карту…</p>:<AddressMap {...{point,kind,label}} data={data.map}/>}
  <p className="address-map-hint" role="status">{point?(kind==='street'?'Показана улица приблизительно. Выберите дом для координат происшествия.':geocoding?.kind==='building'?'Точка внутри контура здания OSM. Вход и квартиру уточните отдельно.':'Точка по введённым координатам.'):'Выберите адрес в подсказках — он появится на карте.'}</p>
  <small className="address-source-note">Локальная копия OSM · дата исходной выгрузки неизвестна. Сведения могут быть неполными. Карту можно перемещать; масштаб — кнопками + / −.</small>
 </div>;
}
