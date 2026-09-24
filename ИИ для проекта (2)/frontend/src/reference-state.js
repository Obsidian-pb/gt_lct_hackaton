const stable=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
export const referenceCurrent=card=>!!card?.reference&&stable(card.reference.source_content)===stable(card.content)&&stable(card.reference.source_scenario||null)===stable(card.caller_scenario||null);
