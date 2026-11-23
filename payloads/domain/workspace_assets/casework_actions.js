"use strict";
function cwEditFact(f){
  if(!f||!cwCurrent(f.anchor)){notice("Capture the passage again from the revised source.");return;}
  cwDialog("Review wording","review-fact",`<blockquote>${e(f.anchor.quote)}</blockquote>`+
    cwField("Factual proposition","wording",{area:true,max:4000,value:f.wording})+
    cwField("Proof element","element",{choices:cwElements(),value:f.element,optional:true})+
    cwField("Evidence role","role",{choices:cwChoices(["Support","Contrary","Context"]),value:f.role})+
    cwField("Speaker or witness","witness",{value:f.witness,optional:true})+cwField("Reviewed by","actor")+
    `<label><input type="checkbox" name="approved" ${f.approved?"checked":""}> I reviewed this wording and the current production for the statement</label>`,"Save wording",f.id);
}
function cwCommit(form){
  const fields=Object.fromEntries([...new FormData(form)].map(([k,v])=>[k,String(v).trim()]));
  const id=form.dataset.id, book=cwBook(), key=id||cwId();
  const put=(list,item)=>{
    const i=list.findIndex(r=>r.id===item.id);
    if(i>=0)list[i]=item;else {if(list.length>=500)throw new Error("The review limit is 500 items of this type.");list.push(item);}
  };
  switch(form.dataset.form){
    case "element":
      put(book.elements,{id:key,...fields});break;
    case "fact":
    case "review-fact":{
      const previous=id?cwFact(id):null, a=previous?.anchor||cwPendingAnchor;
      if(!a||!cwCurrent(a))throw new Error("The selected quotation no longer resolves.");
      if(fields.pin&&!fields.verified_pin)throw new Error("Verify the pinpoint against the original or clear it.");
      put(book.facts,{id:key,anchor:{...a,pin:previous?a.pin:fields.pin||""},element:fields.element,role:fields.role,
        wording:fields.wording,actor:fields.actor,witness:fields.witness,approved:!!fields.approved,
        reviewed_snapshot:W.snapshot_id,checked_versions:cwCheckedVersions(cwImpacts().byElement.get(fields.element)),binding:"current"});
      cwPendingAnchor=null;break;
    }
    case "task":{
      const t=book.tasks.find(x=>x.id===id);
      const same=t&&t.closure===fields.closure&&t.record===fields.record&&t.element===fields.element;
      put(book.tasks,{id:key,...fields,closing_fact:same?t.closing_fact:"",resolution:same?t.resolution:"",closed_by:same?t.closed_by:""});break;
    }
    case "close-task":{
      const t=book.tasks.find(x=>x.id===id),f=cwFact(fields.fact);
      if(!f||!cwCurrent(f.anchor)||f.role!=="Support"||(t.element&&f.element!==t.element))throw new Error("Choose current supporting evidence for this question.");
      Object.assign(t,{closing_fact:f.id,resolution:fields.resolution,closed_by:fields.actor});break;
    }
    case "outline":{
      const f=cwFact(fields.statement),x=cwFact(fields.exhibit);
      if(!f||!x||f.id===x.id||!cwWitnessMatch(f,fields.witness)||f.element!==fields.element||x.element!==fields.element)
        throw new Error("Choose the witness’s own statement and a different exhibit for the same element.");
      if(!cwCurrent(f.anchor)||!cwCurrent(x.anchor))throw new Error("Recheck both passages before saving.");
      put(book.outlines,{id:key,...fields,checked_versions:cwCheckedVersions(cwImpacts().byElement.get(fields.element))});break;
    }
    case "event":{
      if(Boolean(fields.from)!==Boolean(fields.to)||(fields.from&&fields.from>fields.to))
        throw new Error("Enter both ends of a supported interval, or leave both empty for an unresolved date.");
      put(book.events,{id:key,...fields});break;
    }
    case "alias":{
      const f=cwFact(fields.fact);
      if(!f||!cwCurrent(f.anchor))throw new Error("Choose a current source passage for this identity decision.");
      if(![fields.person,fields.alias].every(s=>cwMentions(f.anchor.quote,s)))
        throw new Error("Choose a quotation that identifies both the person and the alias.");
      if(cwAliases().some(a=>a.alias.toLowerCase()===fields.alias.toLowerCase()))
        throw new Error("This alias already has a confirmed link. Reverse it before reassigning.");
      put(book.aliases,{id:key,...fields,at:new Date().toISOString(),reverses:""});break;
    }
    case "reverse":{
      const a=book.aliases.find(x=>x.id===id);
      put(book.aliases,{...a,id:cwId(),reverses:id,actor:fields.actor,at:new Date().toISOString()});break;
    }
    default:throw new Error("Unknown review action.");
  }
}
document.addEventListener("mousedown",ev=>{
  if(ev.target.closest('[data-action="cw-capture"]'))ev.preventDefault();
});
document.addEventListener("submit",ev=>{
  if(!W.casework||W.package_mode==="approved_excerpt_briefing")return;
  const form=ev.target;
  if(form.id==="cw-witness-filter"){
    ev.preventDefault();const data=new FormData(form);
    cwWitness=data.get("witness");cwIssue=data.get("element");renderedState="";render();
  }else if(form.id==="cw-editor"){
    ev.preventDefault();
    try{
      cwCommit(form);
      document.getElementById("review-dialog").close();
      cwRepaint("Review work recorded. Save a copy or export review decisions to retain it.");
    }catch(err){form.querySelector(".cw-error").textContent=err.message;}
  }
});
document.addEventListener("click",async ev=>{
  const button=ev.target.closest("[data-action]"),action=button?.dataset.action;
  if(!action?.startsWith("cw-")||!W.casework||W.package_mode==="approved_excerpt_briefing")return;
  const id=button.dataset.id, book=cwBook();
  try{
    switch(action){
      case "cw-read":return cwRead(id);
      case "cw-capture":return cwCaptureEditor();
      case "cw-add-element":return cwElementEditor();
      case "cw-review-fact":return cwEditFact(cwFact(id));
      case "cw-task-element":return cwTaskEditor({}, {element:id});
      case "cw-track-gap":{
        const item=W.gaps.find(g=>g.id===id)||W.reading_tasks.find(g=>g.id===id);
        return cwTaskEditor({}, {origin:id,record:item.requested_record||item.record||item.question,closure:item.closure_condition||item.closure,
          owner:item.owner==="Unassigned"?"":item.owner,target:item.internal_target});
      }
      case "cw-edit-task":return cwTaskEditor(book.tasks.find(t=>t.id===id));
      case "cw-close-task":return cwCloseEditor(book.tasks.find(t=>t.id===id));
      case "cw-reopen-task":Object.assign(book.tasks.find(t=>t.id===id),{closed_by:"",closing_fact:"",resolution:""});break;
      case "cw-outline-element":cwIssue=id;return goto({view:"Witness preparation",source:null});
      case "cw-add-outline":return cwOutlineEditor("",id);
      case "cw-edit-outline":return cwOutlineEditor(id);
      case "cw-inspect-outline":{
        const o=book.outlines.find(x=>x.id===id);cwIssue=o.element;cwWitness=o.witness;return goto({view:"Witness preparation",source:null});
      }
      case "cw-add-alias":return cwAliasEditor(id);
      case "cw-reverse-alias":return cwDialog("Reverse identity link","reverse",cwField("Reviewed by","actor"),"Reverse link",id);
      case "cw-add-event":return cwEventEditor();
      case "cw-statement":return await cwDownloadWord("statement");
      case "cw-review-word":return await cwDownloadWord("review");
      case "cw-outline-word":return await cwDownloadWord("outline",id);
      default:return;
    }
    cwRepaint("Review work updated in this page.");
  }catch(err){notice(err.message);}
});
