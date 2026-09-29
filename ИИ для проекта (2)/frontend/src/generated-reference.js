// An AI-created card is the source of truth for its own expected field values.
// Keep the internal reference shape so existing training and grading still work.
export function generatedReference(card,meta){
 const fields=card.content.fields;
 const expected=Object.fromEntries(Object.keys(meta.reference_fields).map(key=>[key,{
  value:key==='phone_callback'&&card.caller_scenario?card.caller_scenario.phone_callback:(fields[key]?.trim()||'Неизвестно'),
  evidence:''
 }]));
 const now=new Date().toISOString();
 return {version:2,origin:'generated-card',source_content:structuredClone(card.content),
  source_scenario:structuredClone(card.caller_scenario||null),generated_at:now,model:card.provenance?.model||'ИИ',
  answer:{expected_fields:expected,summary:card.content.fields.description||card.content.report||card.content.title,
   classification_reason:'Тип происшествия указан в утверждаемой карточке.',
   services_reason:'Состав служб указан в утверждаемой карточке.',
   questions:[],critical_errors:['Искажение сведений заявителя или внесение неподтверждённых данных.']}};
}
