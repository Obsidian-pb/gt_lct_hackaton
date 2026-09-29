import React from 'react';

export const CALLER_ROLES=['Неизвестно','Очевидец','Пострадавший','Участник','Родственник'];

export default function CallerRoleSelect({id,value='',disabled=false,onChange,...props}){
 const choices=CALLER_ROLES.includes(value)||!value?CALLER_ROLES:[value,...CALLER_ROLES];
 return <select id={id} value={value} disabled={disabled} onChange={onChange} {...props}>
  <option value="">Выберите статус</option>
  {choices.map(role=><option key={role} value={role}>{role}</option>)}
 </select>;
}
