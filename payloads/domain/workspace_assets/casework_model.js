"use strict";
const cwSourceCache = new Map();
let cwIndex, cwPendingAnchor, cwWitness = "", cwIssue = "";
const cwBook = () => W.casework;
const cwFact = id => cwBook().facts.find(f=>f.id===id);
const cwElement = id => cwBook().elements.find(el=>el.id===id);
const cwId = () => crypto.randomUUID();
function cwOffsets(source) {
  if (!cwSourceCache.has(source.source_id)) {
    const text=source.text||"", pairs=[];
    for(const match of text.matchAll(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g))pairs.push(match.index-pairs.length);
    cwSourceCache.set(source.source_id,{pairs,length:text.length-pairs.length});
  }
  return cwSourceCache.get(source.source_id);
}
function cwNativeOffset(pairs,index){
  let lo=0,hi=pairs.length;
  while(lo<hi){const mid=Math.floor((lo+hi)/2);if(pairs[mid]<index)lo=mid+1;else hi=mid;}
  return index+lo;
}
function cwSlice(source,start,end){
  const {pairs,length}=cwOffsets(source);
  return source.text.slice(cwNativeOffset(pairs,start),cwNativeOffset(pairs,end??length));
}
function cwLength(text){
  return text.length-(text.match(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g)||[]).length;
}
function cwCurrent(anchor) {
  const s=sourceById.get(anchor.source);
  return s && s.text!=null && s.content_sha256===anchor.hash && anchor.end>anchor.start &&
    cwSlice(s,anchor.start,anchor.end)===anchor.quote;
}
function cwLocator(a) {
  const s=sourceById.get(a.source);
  const pages=cwCurrent(a)?(s.page_spans||[]).filter(p=>p[1]<a.end && p[2]>a.start):[];
  const page=pages.length?"PDF p. "+[...new Set(pages.map(p=>p[0]))].join("–"):"";
  return [s?.relative_path||a.source,page,a.pin,"chars "+a.start+"–"+a.end].filter(Boolean).join(" · ");
}
function cwRegister(id,a) {
  if(!cwCurrent(a))return false;
  evidenceById.set(id,{evidence_id:id, source_id:a.source, content_sha256:a.hash, start_offset:a.start, end_offset:a.end, text:a.quote});
  return true;
}
function cwAnchor(source,start,end) {
  return {source:source.source_id,hash:source.content_sha256,start,end,quote:cwSlice(source,start,end),pin:""};
}
function cwIndexData() {
  if(cwIndex)return cwIndex;
  const data=W.case_query_index;
  const units=new Map(), sourceDates=new Map();
  const add=(map,key,value)=>{if(!map.has(key))map.set(key,[]);map.get(key).push(value);};
  for(const [id,sid,start,end] of data.units){
    const s=sourceById.get(sid);
    if(s?.text!=null && start>=0 && end<=cwOffsets(s).length && end>start)units.set(id,{id,sid,start,end});
  }
  for(const row of data.dates)if(units.has(row.unit_id)){
    if(["Record date","Testimony given","Signed"].includes(row.meaning))
      add(sourceDates,units.get(row.unit_id).sid,row);
  }
  for(const ev of W.temporal.events)for(const sid of ev.source_ids){
    if(ev.time.earliest)add(sourceDates,sid,{earliest:ev.time.earliest.slice(0,10),latest:(ev.time.latest||ev.time.earliest).slice(0,10),meaning:"Email header date"});
  }
  for(const ev of W.financial_review?.events||[])if(ev.event_date && !sourceDates.has(ev.source_id) && /record date/i.test(ev.date_basis||""))
    add(sourceDates,ev.source_id,{earliest:ev.event_date,latest:ev.event_date,meaning:ev.date_basis});
  cwIndex={units,sourceDates};
  return cwIndex;
}
function cwUnitAnchor(unit){
  return cwAnchor(sourceById.get(unit.sid),unit.start,unit.end);
}
function cwRead(id){
  const fact=cwFact(id);
  const unit=cwIndexData().units.get(id);
  const a=fact?.anchor || (unit && cwUnitAnchor(unit));
  if(!a || !cwRegister("work-"+id,a)){notice("This passage needs a current source version.");return;}
  goto({source:"work-"+id,sourceIsEvidence:true});
}
function cwGetSelection(){
  const s=sourceById.get(evidenceById.get(state.source)?.source_id||state.source);
  if(!s||s.text==null)return null;
  const sel=window.getSelection();
  if(sel.rangeCount && !sel.isCollapsed){
    const range=sel.getRangeAt(0);
    const startNode=range.startContainer;
    const root=(startNode.nodeType===1?startNode:startNode.parentElement)?.closest("#source-dialog .source-text, #source-dialog .source-excerpt");
    if(!root||!root.contains(range.endContainer))return null;
    const before=range.cloneRange();before.selectNodeContents(root);before.setEnd(range.startContainer,range.startOffset);
    const start=Number(root.dataset.start||0)+cwLength(before.toString()), quote=range.toString(), end=start+cwLength(quote);
    if(quote.trim()&&end-start<=4000&&cwSlice(s,start,end)===quote)return cwAnchor(s,start,end);
  }
  const p=state.sourceIsEvidence && evidenceById.get(state.source);
  return p && p.end_offset-p.start_offset<=4000?cwAnchor(s,p.start_offset,p.end_offset):null;
}
function cwAliases(){
  const records=cwBook().aliases;
  const undone=new Set(records.map(x=>x.reverses).filter(Boolean));
  return records.filter(x=>!x.reverses&&!undone.has(x.id)&&cwCurrent(cwFact(x.fact)?.anchor||{}));
}
const cwNamePatterns=new Map();
function cwMentions(text,label){
  if(!label)return false;
  if(!cwNamePatterns.has(label)){
    const escaped=label.replace(/[.*+?^${}()|[\]\\]/g,char=>"\\"+char);
    cwNamePatterns.set(label,new RegExp("(?<![\\p{L}\\p{N}_])"+escaped+"(?![\\p{L}\\p{N}_])","iu"));
  }
  return cwNamePatterns.get(label).test(text);
}
function cwNames(name){
  const normalize=s=>s.trim().toLowerCase();
  const names=new Set([normalize(name)]);
  for(const link of cwAliases())if(normalize(link.person)===normalize(name))names.add(normalize(link.alias));
  return names;
}
function cwWitnessMatch(f,name) {
  return !!f?.witness && cwNames(name).has(f.witness.trim().toLowerCase());
}
function cwRepaint(message) {
  markUnsaved("review");renderedState="";render();if(message)notice(message);
}
function cwRow(text,body="") {return `<article class="cw-row"><strong>${e(text)}</strong>${body}</article>`;}
function cwButton(id,label="Open passage"){return btn(label,"cw-read",id);}
function cwFactRow(f){
  const current=cwCurrent(f.anchor);
  return cwRow(f.wording,`<small>${e(f.role)} · ${e(f.actor)} · ${e(cwLocator(f.anchor))}</small><blockquote>${e(f.anchor.quote)}</blockquote>
    ${current?cwButton(f.id):'<p>Earlier reviewed excerpt. Capture the revised source to use this wording again.</p>'}`);
}
function cwTargetDate(value) {
  if(!value)return false;
  const today=new Date();today.setHours(0,0,0,0);
  return new Date(value+"T00:00:00") < today;
}
