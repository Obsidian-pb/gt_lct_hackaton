import {useEffect,useMemo,useRef,useState} from 'react';

export default function AddressMap({data,point,kind,label}){
 const canvas=useRef(null),drag=useRef(null),[view,setView]=useState({x:0,y:0,scale:.035});
 const origin=useMemo(()=>{const points=data?.boundary||[];if(!points.length)return [0,0];return [points.reduce((sum,p)=>sum+p[0],0)/points.length,points.reduce((sum,p)=>sum+p[1],0)/points.length];},[data]);
 const project=([lon,lat])=>[(lon-origin[0])*111200*Math.cos(origin[1]*Math.PI/180),(origin[1]-lat)*111200];
 const center=()=>{const [x,y]=point?project(point):[0,0];setView({x,y,scale:point?(kind==='street'?.18:.65):.035});};
 useEffect(center,[point?.[0],point?.[1],kind]);
 const zoom=factor=>setView(v=>({...v,scale:Math.max(.018,Math.min(3,v.scale*factor))}));
 useEffect(()=>{
  const el=canvas.current;if(!el||!data)return;
  const render=()=>{
   const rect=el.getBoundingClientRect(),w=rect.width,h=rect.height,dpr=window.devicePixelRatio||1;
   el.width=w*dpr;el.height=h*dpr;const ctx=el.getContext('2d');ctx.scale(dpr,dpr);ctx.fillStyle='#eef3f2';ctx.fillRect(0,0,w,h);
   const screen=p=>{const [x,y]=project(p);return [(x-view.x)*view.scale+w/2,(y-view.y)*view.scale+h/2];};
   const path=points=>{points.forEach((p,i)=>{const [x,y]=screen(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});};
   ctx.beginPath();path(data.boundary);ctx.closePath();ctx.fillStyle='#f8faf6';ctx.fill();ctx.strokeStyle='#c0d4c3';ctx.stroke();
   ctx.lineCap='round';
   for(const road of data.roads){ctx.beginPath();path(road.points);ctx.strokeStyle='#fff';ctx.lineWidth=Math.max(1.4,view.scale*(/primary|secondary|tertiary/.test(road.type)?13:7));ctx.stroke();}
   for(const building of data.buildings){ctx.beginPath();for(const ring of building.rings){path(ring);ctx.closePath();}ctx.fillStyle='#cdd6dc';ctx.fill('evenodd');ctx.strokeStyle='#aebdc7';ctx.lineWidth=.5;ctx.stroke();}
   ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='11px Arial';
   const occupied=[];const text=(value,p,color)=>{const [x,y]=screen(p);if(x<35||x>w-35||y<15||y>h-15)return;const width=ctx.measureText(value).width+10;if(occupied.some(b=>Math.abs(b.x-x)<(b.width+width)/2&&Math.abs(b.y-y)<19))return;occupied.push({x,y,width});ctx.strokeStyle='#f8faf6';ctx.lineWidth=3;ctx.strokeText(value,x,y);ctx.fillStyle=color;ctx.fillText(value,x,y);};
   if(view.scale>.12){for(const road of data.roads){if(road.name)text(road.name,road.points[Math.floor(road.points.length/2)],'#5f7480');}}
   if(view.scale>.45){for(const building of data.buildings){if(building.house)text(building.house,building.point,'#354c5b');}}
   if(point){const [x,y]=screen(point);ctx.beginPath();ctx.arc(x,y,kind==='street'?15:10,0,Math.PI*2);ctx.fillStyle=kind==='street'?'#1998e540':'#e44848';ctx.fill();ctx.lineWidth=3;ctx.strokeStyle=kind==='street'?'#1687bd':'#fff';ctx.stroke();ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fillStyle=kind==='street'?'#1687bd':'#fff';ctx.fill();}
   const meters=100/view.scale,rounded=10**Math.floor(Math.log10(meters)),length=Math.floor(meters/rounded)*rounded;
   ctx.strokeStyle='#526777';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(16,h-35);ctx.lineTo(16+length*view.scale,h-35);ctx.stroke();ctx.textAlign='left';ctx.fillStyle='#344b5c';ctx.fillText(length>=1000?`${length/1000} км`:`${length} м`,16,h-46);
  };
  render();const observer=new ResizeObserver(render);observer.observe(el);return()=>observer.disconnect();
 },[data,view,point?.[0],point?.[1],kind]);
 return <div className="address-map" data-map-kind={point?kind:'none'} data-map-point={point?.join(',')||''}>
  <canvas ref={canvas} role="img" aria-label={point?`Карта: ${label}. ${kind==='street'?'Примерное положение улицы':'Точка по координатам карточки'}`:'Карта '+(data?.city||'учебного города')} tabIndex={0}
   onKeyDown={e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();setView(v=>({...v,x:v.x+(e.key==='ArrowLeft'?-80:e.key==='ArrowRight'?80:0)/v.scale,y:v.y+(e.key==='ArrowUp'?-80:e.key==='ArrowDown'?80:0)/v.scale}));}if(e.key==='+'||e.key==='=')zoom(1.5);if(e.key==='-')zoom(1/1.5);}}
   onPointerDown={e=>{drag.current={x:e.clientX,y:e.clientY,view};e.currentTarget.setPointerCapture(e.pointerId);}}
   onPointerMove={e=>{if(drag.current){const d=drag.current;setView({...d.view,x:d.view.x-(e.clientX-d.x)/d.view.scale,y:d.view.y-(e.clientY-d.y)/d.view.scale});}}}
   onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}/>
  <div className="address-map-controls"><button type="button" onClick={()=>zoom(1.5)} aria-label="Приблизить карту">+</button><button type="button" onClick={()=>zoom(1/1.5)} aria-label="Отдалить карту">−</button><button type="button" onClick={center} aria-label="Показать адрес на карте">⌖</button></div>
  <a className="osm-credit" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a>
 </div>;
}
