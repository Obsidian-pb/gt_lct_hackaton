import {useEffect} from 'react';
import TeacherBoard from './TeacherBoard.jsx';
import TrainingBuilder from './TrainingBuilder.jsx';
import CurriculumBuilder from './CurriculumBuilder.jsx';
import ClassroomTrainingBuilder from './ClassroomTrainingBuilder.jsx';
export const statusNames={awaiting_call:'Ожидает вызова',queued:'Ожидает предыдущую',active:'В процессе',submitted:'Ожидает проверки',pending_teacher:'Проверка преподавателя',reviewed:'Проверена'};
export const duration=n=>n==null?'—':`${Math.floor(n/3600).toString().padStart(2,'0')}:${Math.floor(n%3600/60).toString().padStart(2,'0')}:${Math.floor(n%60).toString().padStart(2,'0')}`;
export function download(name,data,type='application/json'){const url=URL.createObjectURL(new Blob([typeof data==='string'?data:JSON.stringify(data,null,2)],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
export function Panel({title,children,actions,className=''}){return <section className={'tw-panel '+className}><header><h2>{title}</h2>{actions}</header><div className="tw-panel-body">{children}</div></section>;}
export function Metrics({items}){return <div className="tw-metrics">{items.map(([label,value])=><div key={label}><small>{label}</small><strong>{value}</strong></div>)}</div>;}
export function Modal({title,onClose,children,wide=false}){useEffect(()=>{const key=e=>{if(e.key==='Escape')onClose();};document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key);},[onClose]);return <dialog className={'tw-modal '+(wide?'wide':'')} ref={el=>{if(el&&!el.open)el.showModal();}} onCancel={e=>{e.preventDefault();onClose();}}><header><h2>{title}</h2><button aria-label="Закрыть окно" onClick={onClose}>×</button></header>{children}</dialog>;}
const ignoreCurrent=()=>{};
export default function TrainingWorkspace({section}){
 const training=['create-training','scenario-builder','legacy-builder','trainings','monitoring'].includes(section);
 return <div className="tw teacher-workspace"><main id="teacher-content" className="teacher-main"><p className="teacher-eyebrow">Панель преподавателя</p>{training&&<nav className="teacher-training-tabs" aria-label="Управление тренировками">{[['trainings','Все тренировки'],['create-training','Создание тренировки'],['monitoring','Мониторинг']].map(([key,label])=><a key={key} aria-current={section===key?'page':undefined} href={'/teacher#'+key}>{label}</a>)}</nav>}{section==='create-training'?<ClassroomTrainingBuilder/>:section==='scenario-builder'?<CurriculumBuilder/>:section==='legacy-builder'?<TrainingBuilder/>:<TeacherBoard section={section} onCurrent={ignoreCurrent}/>}</main></div>;
}
