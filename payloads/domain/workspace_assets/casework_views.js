"use strict";
const cwRoutes=[["Issue review","Issues & evidence"],["Proof chart","Proof chart"],["Discovery","Discovery tracker"]];
function cwOptions(items, selected){
  return items.map(([value,label])=>`<option value="${e(value)}" ${value===selected?"selected":""}>${e(label)}</option>`).join("");
}
function cwField(label,name,options={}) {
  const {value="", choices, emptyLabel="No options available", area, type="text",optional=false,max=500}=options;
  const attrs=`name="${e(name)}" aria-label="${e(label)}" ${optional?"":"required"}`;
  let input;
  if(choices?.length===0)input=`<select ${attrs} disabled><option value="">${e(emptyLabel)}</option></select>`;
  else if(choices)input=`<select ${attrs}>${cwOptions(choices,value)}</select>`;
  else if(area)input=`<textarea ${attrs} maxlength="${max}">${e(value)}</textarea>`;
  else input=`<input ${attrs} type="${type}" maxlength="${max}" value="${e(value)}">`;
  return `<label>${e(label)}${input}</label>`;
}
const cwChoices=items=>items.map(v=>[v,v]);
const cwElements=()=>[["","Choose an element"],...cwBook().elements.map(el=>[el.id,el.group+" · "+el.title])];
function cwFactChoices(items,label="Choose a fact"){return [["",label],...items.map(f=>[f.id,f.wording])];}
function cwDialog(title,form,fields,submit,id=""){
  const dialog=document.getElementById("review-dialog");
  dialog.innerHTML=`<h2>${e(title)}</h2><form id="cw-editor" class="cw-form" data-form="${e(form)}" data-id="${e(id)}">${fields}<p role="alert" class="cw-error"></p><div class="actions"><button type="submit" class="primary">${e(submit)}</button>${btn("Cancel","close-review")}</div></form>`;
  if(!dialog.open)dialog.showModal();
  reportUI.enhance(dialog);
}
function cwElementEditor(){
  cwDialog("Define a proof element","element",cwField("Type","kind",{choices:cwChoices(["Claim","Defense","Issue"])})+
    cwField("Claim, defense or issue","group")+cwField("Fact to establish","title"),"Add element");
}
function cwCaptureEditor(){
  const a=cwGetSelection();
  if(!a){notice("Select up to 4,000 characters in the source text, then choose Capture fact.");return;}
  cwPendingAnchor=a;
  cwDialog("Capture a cited fact","fact",`<blockquote>${e(a.quote)}</blockquote><small>${e(cwLocator(a))}</small>`+
    cwField("Factual proposition","wording",{area:true,max:4000})+
    cwField("Proof element","element",{choices:cwElements(),optional:true})+
    cwField("Evidence role","role",{choices:cwChoices(["Context","Support","Contrary"])})+
    cwField("Speaker or witness, if attributed in the source","witness",{optional:true})+
    cwField("Your name","actor")+cwField("Bates or transcript page and line, if verified","pin",{optional:true})+
    '<label><input type="checkbox" name="verified_pin"> I checked this pinpoint against the original</label>'+
    '<label><input type="checkbox" name="approved"> I reviewed this wording for the statement of facts</label>',"Save fact");
}
function cwProofView(){
  const book=cwBook();
  return `<section class="cw-section"><h2>Proof chart</h2>${routeTabs(cwRoutes)}<div class="actions">${btn("Add element","cw-add-element","",'class="primary"')}${btn("Capture from evidence","view","Evidence Explorer")}</div>
    ${W.casework_import_note?empty(W.casework_import_note):""}
    ${book.elements.map(el=>{
      const facts=book.facts.filter(f=>f.element===el.id);
      const support=facts.filter(f=>f.role==="Support"&&cwCurrent(f.anchor));
      const contrary=facts.filter(f=>f.role==="Contrary"&&cwCurrent(f.anchor));
      const versions=new Set(support.map(f=>f.anchor.hash));
      return `<article class="card"><small>${e(el.kind)} · ${e(el.group)}</small><h3>${e(el.title)}</h3>
        <p>${versions.size?e(versions.size+" distinct supporting source version"+(versions.size===1?"":"s")):"Open proof gap · No current supporting fact linked."} · ${contrary.length} contrary fact${contrary.length===1?"":"s"}</p>
        ${facts.map(cwFactRow).join("")}${btn("Track discovery gap","cw-task-element",el.id)} ${btn("Prepare witness","cw-outline-element",el.id)}</article>`;
    }).join("")||empty("Add the first fact counsel needs to establish.")}
    ${book.facts.some(f=>!f.element)?"<h3>Unassigned facts</h3>"+book.facts.filter(f=>!f.element).map(cwFactRow).join(""):""}</section>`;
}
function cwTasksView(){
  const book=cwBook();
  return `<section class="cw-section"><h2>Discovery tracker</h2>${routeTabs(cwRoutes)}${btn("Add discovery task","cw-task-element")}
    ${book.tasks.map(t=>{
      const f=cwFact(t.closing_fact),closed=!!f&&cwCurrent(f.anchor)&&f.role==="Support"&&(!t.element||t.element===f.element);
      return cwRow(t.record,`<p>${e(t.owner)} · ${e(t.target||"No internal target")} · ${closed?"Closed":f?"Reopen · evidence changed":cwTargetDate(t.target)?"Overdue":"Open"}</p>
        <p>Closure test: ${e(t.closure)}</p>${f?`<p>${e(t.closed_by)} · ${e(t.resolution)}</p>${cwFactRow(f)}`:""}
        ${btn("Edit task","cw-edit-task",t.id)} ${!closed?btn("Record resolution","cw-close-task",t.id):btn("Reopen task","cw-reopen-task",t.id)}`);
    }).join("")||empty("Track a gap to assign its next source check.")}
    <h3>Suggested source checks</h3>${[...W.gaps.map(g=>[g.id,g.question]),...(W.reading_tasks||[]).map(t=>[t.id,t.title])].map(([id,title])=>cwRow(title,btn("Track this gap","cw-track-gap",id))).join("")||empty("No suggested checks in this report.")}</section>`;
}
function cwTaskEditor(t={},origin={}){
  const x={...origin,...t};
  cwDialog(t.id?"Edit discovery task":"Track a discovery gap","task",
    cwField("Record sought","record",{value:x.record})+cwField("What would resolve the question?","closure",{value:x.closure,area:true,max:4000})+
    cwField("Proof element","element",{choices:cwElements(),value:x.element,optional:true})+
    cwField("Owner","owner",{value:x.owner})+cwField("Internal target","target",{type:"date",value:x.target,optional:true})+
    `<input type="hidden" name="origin" value="${e(x.origin||"")}">`,"Save task",t.id);
}
function cwCloseEditor(t){
  const facts=cwBook().facts.filter(f=>(!t.element||t.element===f.element)&&f.role==="Support"&&cwCurrent(f.anchor));
  cwDialog("Record task resolution","close-task",`<p>${e(t.closure)}</p>`+
    cwField("Evidence that meets the closure test","fact",{choices:cwFactChoices(facts)})+
    cwField("How this passage resolves the request","resolution",{area:true,max:4000})+cwField("Reviewed by","actor"),"Close task",t.id);
}
function cwWitnesses(){
  return [...new Set([...cwBook().facts.map(f=>f.witness),...cwAliases().map(a=>a.person)].filter(Boolean))].sort();
}
function cwOutlinesView(){
  const book=cwBook(), witnesses=cwWitnesses();
  const witness=cwWitness||witnesses[0]||"", issue=cwIssue||book.elements[0]?.id||"";
  const impacted=cwImpacts().byElement.get(issue);
  const rows=book.outlines.filter(o=>o.element===issue && o.witness===witness);
  const canChoose=witnesses.length>0 && book.elements.length>0;
  let emptyMessage="Select a witness and issue with a cited statement and comparison exhibit.";
  if(!book.elements.length)emptyMessage="Start by adding a proof element in the proof chart.";
  else if(!witnesses.length)emptyMessage="Open a source in Evidence and capture a statement with the witness’s name.";
  return `<section class="cw-section"><h2>Witness preparation</h2>${peopleTabs()}
    <form id="cw-witness-filter" class="cw-form">${cwField("Witness","witness",{choices:cwChoices(witnesses),value:witness,emptyLabel:"No witnesses recorded"})}
    ${cwField("Proof element","element",{choices:book.elements.length?cwElements():[],value:issue,emptyLabel:"No proof elements defined"})}<button ${canChoose?"":"disabled"}>Choose witness and issue</button></form>
    <div class="actions">${btn("Add comparison question","cw-add-outline",issue,witness&&issue?'':'disabled') } ${rows.length?btn("Download editable outline","cw-outline-word",issue):""}</div>
    ${rows.map(o=>cwRow(o.question,`<div class="cw-split"><div><h4>Witness statement</h4>${cwFactRow(cwFact(o.statement))}</div><div><h4>Comparison exhibit</h4>${cwFactRow(cwFact(o.exhibit))}</div></div><p>${e(o.resolution||"Discrepancy awaiting review")}</p>${cwOutlineNeedsReview(o,impacted)?"<p>Recheck this question against the current evidence and attribution.</p>":""}${btn("Edit question or resolution","cw-edit-outline",o.id)}`)).join("")||empty(emptyMessage)}</section>`;
}
function cwOutlineEditor(id,el){
  const o=cwBook().outlines.find(row=>row.id===id)||{}, issue=o.element||el, witness=o.witness||cwWitness||cwWitnesses()[0]||"";
  const facts=cwBook().facts.filter(f=>f.element===issue&&cwCurrent(f.anchor));
  if(!issue||!witness){notice("Capture an attributed statement and link it to a proof element first.");return;}
  cwDialog("Deposition question","outline",`<p>${e(witness)} · ${e(cwElement(issue)?.title)}</p><input type="hidden" name="witness" value="${e(witness)}"><input type="hidden" name="element" value="${e(issue)}">`+
    cwField("Witness’s own statement","statement",{choices:cwFactChoices(facts.filter(f=>cwWitnessMatch(f,witness))),value:o.statement})+
    cwField("Comparison exhibit","exhibit",{choices:cwFactChoices(facts),value:o.exhibit})+
    cwField("Neutral follow-up question","question",{area:true,value:o.question||"What explains the difference between these two accounts?",max:4000})+
    cwField("Counsel’s explanation or resolution","resolution",{area:true,value:o.resolution,optional:true,max:4000}),"Save question",id);
}
function cwIdentityView(){
  const aliases=cwAliases();
  return `<section class="cw-section"><h2>Identity review</h2>${peopleTabs()}
    <p>Confirm an identity from a cited passage. Shared mailboxes and namesakes keep their original records.</p>${btn("Review an alias","cw-add-alias")}
    ${cwBook().aliases.map(a=>cwRow(a.alias+" → "+a.person,`<p>${e(a.actor)} · ${e(a.at)} · ${a.reverses?"Reversal":aliases.some(x=>x.id===a.id)?"Confirmed":"Inactive"}</p>
       ${cwButton(a.fact)} ${aliases.some(x=>x.id===a.id)?btn("Reverse link","cw-reverse-alias",a.id):""}`)).join("")}
    <h3>Observed names and addresses</h3>${W.temporal.nodes.map(n=>cwRow((n.names||[]).join(" / ")||n.id,`<small>${e(n.id)}</small>${btn("Review address","cw-add-alias",n.id)}`)).join("")||empty("No observed email identities in this scope.")}</section>`;
}
function cwAliasEditor(alias=""){
  cwDialog("Confirm an identity link","alias",cwField("Person","person")+cwField("Name, title or address on the record","alias",{value:alias})+
    cwField("Passage establishing this link","fact",{choices:cwFactChoices(cwBook().facts.filter(f=>cwCurrent(f.anchor)))})+
    cwField("Reviewed by","actor"),"Confirm link");
}
function cwChronology(){
  const idx=cwIndexData(), rows=[];
  const sourceIds=new Set(W.sources.filter(s=>(!state.sourceIds||state.sourceIds.includes(s.source_id))&&(!state.query||String(s.text||"").toLowerCase().includes(state.query.toLowerCase()))).map(s=>s.source_id));
  if(state.address){
    const addressed=new Set(W.temporal.events.filter(ev=>Object.values(ev.fields.headers).flat().includes(state.address)).flatMap(ev=>ev.source_ids));
    for(const sid of sourceIds)if(!addressed.has(sid))sourceIds.delete(sid);
  }
  function add(sid,from,to,when,meaning,lane,label,link){
    if(!sourceIds.has(sid) || ((state.from||state.to)&&(!from||(state.from&&to<state.from)||(state.to&&from>state.to))))return;
    rows.push({from:from||"9999",when,meaning,lane,label,link});
  }
  for(const ev of W.temporal.events)add(ev.source_ids[0],ev.time.earliest?.slice(0,10),(ev.time.latest||ev.time.earliest)?.slice(0,10),ev.display,"Header date","Communication",ev.title,evidenceButtons(ev.evidence_refs.map(p=>p.evidence_id)));
  for(const ev of W.financial_review?.events||[])add(ev.source_id,ev.event_date,ev.event_date,ev.event_date||"Date unresolved",ev.date_basis,"Financial record",ev.quote,evidenceButtons(ev.evidence_ids));
  for(const d of W.case_query_index.dates){
    const u=idx.units.get(d.unit_id);if(!u)continue;
    add(u.sid,d.earliest,d.latest,d.wording,d.meaning,d.lane,cwUnitAnchor(u).quote,cwButton(u.id));
  }
  for(const ev of cwBook().events){
    const f=cwFact(ev.fact);if(f&&cwCurrent(f.anchor))add(f.anchor.source,ev.from,ev.to,ev.when,ev.meaning,ev.lane,ev.label,cwButton(f.id));
  }
  rows.sort((a,b)=>a.from.localeCompare(b.from));
  return `<h2>Timeline</h2><p>Dates retain their source wording. A statement date and the event it describes appear separately. Early, mid and late month are displayed as approximate intervals for ordering.</p>${btn("Add event from a fact","cw-add-event")}
    <div class="timeline reading-timeline">${rows.slice(0,200).map(r=>cwRow(r.when+" · "+r.meaning,`<small>${e(r.lane)}</small><p>${e(r.label)}</p>${r.link}`)).join("")||empty("No dated records in the selected scope.")}</div>
    <small>${Math.min(rows.length,200)} of ${rows.length} matching date entries shown. Narrow the date or source filters to focus.</small><details><summary>Inspect transaction arithmetic</summary>${transactionReview()}</details>`;
}
function cwEventEditor(){
  cwDialog("Add a cited event","event",cwField("Source fact","fact",{choices:cwFactChoices(cwBook().facts.filter(f=>cwCurrent(f.anchor)))})+
    cwField("Event","label")+cwField("Type","lane",{choices:cwChoices(["Contract","Notice","Testimony","Business record","Reported event"])})+
    cwField("Date describes","meaning",{choices:cwChoices(["Reported event","Record date","Termination","Testimony given"])})+
    cwField("Date as stated or qualified","when")+cwField("Earliest supported day","from",{type:"date",optional:true})+
    cwField("Latest supported day","to",{type:"date",optional:true}),"Add to chronology");
}
