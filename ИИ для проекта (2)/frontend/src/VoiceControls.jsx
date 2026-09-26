import {useEffect,useRef,useState} from 'react';
import {api} from './api.js';
export default function VoiceControls({history,setQuestion,disabled}){
 const [listening,setListening]=useState(false),[message,setMessage]=useState(''),[speak,setSpeak]=useState(false),[tts,setTts]=useState({available:false,engine:'browser',voices:[]}),recognizer=useRef(null),audio=useRef(null),seen=useRef(history.at(-1)?.id);
 useEffect(()=>{let live=true;api('tts_status').then(x=>{if(live)setTts(x);}).catch(()=>{});return()=>{live=false;};},[]);
 const stopSound=()=>{if(audio.current){audio.current.pause();audio.current.src='';audio.current=null;}window.speechSynthesis?.cancel();};
 const browserSay=text=>{if(!window.speechSynthesis){setMessage('Озвучивание недоступно в этом браузере.');return;}const phrase=new SpeechSynthesisUtterance(text);phrase.lang='ru-RU';phrase.rate=1;const voice=speechSynthesis.getVoices().find(v=>v.lang.startsWith('ru'));if(voice)phrase.voice=voice;speechSynthesis.speak(phrase);};
 const say=async text=>{stopSound();if(tts.available){try{const result=await api('tts_synthesize',{text,voice:tts.voices?.[0]});const player=new Audio(result.audio);audio.current=player;await player.play();setMessage('');return;}catch{setMessage('Piper сейчас недоступен — использован системный голос браузера.');}}browserSay(text);};
 useEffect(()=>{const last=history.at(-1);if(last&&last.id!==seen.current){seen.current=last.id;if(speak&&['caller','service'].includes(last.role))say(last.text);}},[history,speak]);
 useEffect(()=>()=>{recognizer.current?.abort();stopSound();},[]);
 useEffect(()=>{if(disabled)recognizer.current?.abort();},[disabled]);
 const microphone=async()=>{
  if(listening){recognizer.current?.stop();return;}
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognition){setMessage('Распознавание речи недоступно. Откройте Chrome/Edge или введите вопрос текстом.');return;}
  setMessage('');setListening(true);stopSound();
  try{
   const stream=await navigator.mediaDevices.getUserMedia({audio:true});stream.getTracks().forEach(track=>track.stop());
   const r=new Recognition();recognizer.current=r;r.lang='ru-RU';r.interimResults=false;r.continuous=false;
   r.onresult=e=>{const text=Array.from(e.results).map(row=>row[0].transcript).join(' ');setQuestion(text.slice(0,2000));setMessage('Проверьте распознанный вопрос и нажмите «Отправить».');};
   r.onerror=e=>{setMessage(e.error==='not-allowed'?'Разрешите микрофон в настройках доступа к этому сайту.':e.error==='no-speech'?'Речь не распознана. Попробуйте ещё раз.':'Не удалось распознать речь. Проверьте подключение или введите вопрос текстом.');setListening(false);};
   r.onend=()=>setListening(false);r.start();
  }catch{setListening(false);setMessage('Нет доступа к микрофону. Разрешите его для этого сайта в настройках браузера.');}
 };
 const last=[...history].reverse().find(x=>['caller','service'].includes(x.role));
 return <div className="student-voice"><div className="student-buttons"><button type="button" id="student-microphone" disabled={disabled} aria-pressed={listening} onClick={microphone}>{listening?'■ Остановить запись':'🎙 Задать вопрос голосом'}</button><button type="button" disabled={!last} onClick={()=>say(last.text)}>▶ Послушать заявителя</button><button type="button" onClick={stopSound}>Остановить звук</button></div><label><input type="checkbox" checked={speak} onChange={e=>setSpeak(e.target.checked)}/> Озвучивать новые ответы</label><small className="student-tts-engine">Озвучивание: {tts.available?'Piper (локально)':'системный голос браузера'}</small>{(message||listening)&&<p role="status">{listening?'Слушаю…':message}</p>}</div>;
}
