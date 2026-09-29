import {useEffect,useState} from 'react';
import {api} from './api.js';
import {readProfile} from './Shell.jsx';
export default function Materials({teacher=false}){
 const [rows,setRows]=useState([]),[title,setTitle]=useState(''),[url,setUrl]=useState(''),[description,setDescription]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const refresh=()=>api('materials_list').then(setRows).catch(e=>setError(e.message));
 useEffect(()=>{refresh();},[]);
 const save=async e=>{e.preventDefault();setBusy(true);setError('');try{await api('materials_add',{title,url,description,teacher:readProfile()});setTitle('');setUrl('');setDescription('');await refresh();}catch(e){setError(e.message);}finally{setBusy(false);}};
 return <section className="student-panel materials"><h2>Методические материалы</h2>{error&&<p role="alert">{error}</p>}{teacher&&<form onSubmit={save}><label>Название<input required maxLength={160} value={title} onChange={e=>setTitle(e.target.value)}/></label><label>Ссылка на PDF, DOCX, XLSX или инструкцию<input required type="url" value={url} onChange={e=>setUrl(e.target.value)}/></label><label>Описание<textarea maxLength={1000} value={description} onChange={e=>setDescription(e.target.value)}/></label><button disabled={busy}>Добавить материал</button></form>}{rows.length?<ul>{rows.map(row=><li key={row.id}><a target="_blank" rel="noreferrer" href={row.url}>{row.title}</a>{row.description&&<p>{row.description}</p>}</li>)}</ul>:<p>Материалов пока нет.</p>}</section>;
}
