import {useEffect,useRef,useState} from 'react';
import {api} from './api.js';

const chunks=text=>{
 const result=[];let rest=text.trim();
 while(rest.length>1150){let end=rest.lastIndexOf(' ',1150);if(end<600)end=1150;result.push(rest.slice(0,end));rest=rest.slice(end).trimStart();}
 if(rest)result.push(rest);
 return result;
};

export default function VoiceControls({history,setQuestion,disabled,voiceId='ru_RU-irina-medium'}){
 const [listening,setListening]=useState(false),[message,setMessage]=useState(''),[speak,setSpeak]=useState(true);
 const [tts,setTts]=useState({available:false,engine:'browser',voices:[],message:''}),[ttsReady,setTtsReady]=useState(false);
 const [audioSrc,setAudioSrc]=useState('');
 const recognizer=useRef(null),player=useRef(null),seen=useRef(null),generation=useRef(0),finishPlayback=useRef(null);
 useEffect(()=>{let live=true;api('tts_status').then(x=>{if(live){setTts(x);setTtsReady(true);}}).catch(e=>{if(live){setTts(x=>({...x,message:e.message}));setTtsReady(true);}});return()=>{live=false;};},[]);
 const stopSound=(clear=false)=>{generation.current++;if(finishPlayback.current){finishPlayback.current();finishPlayback.current=null;}if(player.current){player.current.pause();player.current.currentTime=0;}window.speechSynthesis?.cancel();if(clear)setAudioSrc('');};
 const browserSay=text=>{if(!window.speechSynthesis){setMessage('Озвучивание недоступно в этом браузере.');return;}const phrase=new SpeechSynthesisUtterance(text);phrase.lang='ru-RU';phrase.rate=1;const browserVoice=speechSynthesis.getVoices().find(v=>v.lang.toLowerCase().startsWith('ru'));if(browserVoice)phrase.voice=browserVoice;speechSynthesis.cancel();speechSynthesis.speak(phrase);};
 const playPrepared=async(src,request)=>{
  if(request!==generation.current)return false;
  setAudioSrc(src);
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  if(request!==generation.current)return false;
  const el=player.current;
  if(!el)return false;
  el.src=src;el.load();
  try{
   await el.play();
  }catch(e){
   if(request!==generation.current)return false;
   setMessage('Аудио готово. Браузер не разрешил автозапуск — нажмите ▶ в плеере ниже.');
   return false;
  }
  await new Promise((resolve,reject)=>{finishPlayback.current=resolve;el.onended=resolve;el.onerror=()=>reject(Error('Не удалось воспроизвести WAV.'));});
  finishPlayback.current=null;
  return request===generation.current;
 };
 const say=async text=>{
  if(!text?.trim())return;
  stopSound(true);const request=generation.current;setMessage('Готовлю озвучивание…');
  if(tts.available){
   try{
    for(const part of chunks(text)){
     if(!tts.voices.includes(voiceId))throw Error('Выбранный преподавателем голос не установлен');
     const result=await api('tts_synthesize',{text:part,voice:voiceId});
     if(request!==generation.current)return;
     const played=await playPrepared(result.audio,request);
     if(!played)return;
    }
    setMessage('');return;
   }catch(e){
    if(request!==generation.current)return;
    setMessage('Piper не смог озвучить реплику: '+e.message+'. Ниже попробуйте голос браузера.');
   }
  }else setMessage(tts.message||'Piper недоступен. Использован русский голос браузера.');
  if(request===generation.current)browserSay(text);
 };
 useEffect(()=>{if(!ttsReady||!speak)return;const last=[...history].reverse().find(x=>['caller','service'].includes(x.role));if(last&&last.id!==seen.current){seen.current=last.id;void say(last.text);}},[history,speak,ttsReady]);
 useEffect(()=>()=>{recognizer.current?.abort();stopSound(true);},[]);
 useEffect(()=>{if(disabled)recognizer.current?.abort();},[disabled]);
 const microphone=async()=>{
  if(listening){recognizer.current?.stop();return;}
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognition){setMessage('Распознавание речи недоступно. Откройте Chrome/Edge или введите вопрос текстом.');return;}
  setMessage('');setListening(true);stopSound(false);
  try{
   const stream=await navigator.mediaDevices.getUserMedia({audio:true});stream.getTracks().forEach(track=>track.stop());
   const r=new Recognition();recognizer.current=r;r.lang='ru-RU';r.interimResults=false;r.continuous=false;
   r.onresult=e=>{const text=Array.from(e.results).map(row=>row[0].transcript).join(' ');setQuestion(text.slice(0,2000));setMessage('Проверьте распознанный вопрос и нажмите «Отправить».');};
   r.onerror=e=>{setMessage(e.error==='not-allowed'?'Разрешите микрофон в настройках доступа к этому сайту.':e.error==='no-speech'?'Речь не распознана. Попробуйте ещё раз.':'Не удалось распознать речь. Проверьте подключение или введите вопрос текстом.');setListening(false);};
   r.onend=()=>setListening(false);r.start();
  }catch{setListening(false);setMessage('Нет доступа к микрофону. Разрешите его для этого сайта в настройках браузера.');}
 };
 const last=[...history].reverse().find(x=>['caller','service'].includes(x.role));
 return <div className="student-voice"><div className="student-buttons"><button type="button" id="student-microphone" disabled={disabled} aria-pressed={listening} onClick={microphone}>{listening?'■ Остановить запись':'🎙 Задать вопрос голосом'}</button><button type="button" id="student-play-voice" disabled={!last} onClick={()=>say(last.text)}>▶ Послушать {last?.role==='service'?'сотрудника службы':'очевидца'}</button><button type="button" onClick={()=>{stopSound(false);setMessage('Звук остановлен.');}}>Остановить звук</button></div><label><input type="checkbox" checked={speak} onChange={e=>{setSpeak(e.target.checked);if(e.target.checked)seen.current=null;else stopSound(false);}}/> Автоматически озвучивать реплики</label><small className="student-tts-engine">Озвучивание: {!ttsReady?'проверяем…':tts.available?'Piper (локально)':'голос браузера'}</small>{audioSrc&&<div className="student-audio-player"><small>Аудио последней реплики</small><audio ref={player} controls preload="auto" src={audioSrc}/></div>}{(message||listening)&&<p role="status">{listening?'Слушаю…':message}</p>}</div>;
}
