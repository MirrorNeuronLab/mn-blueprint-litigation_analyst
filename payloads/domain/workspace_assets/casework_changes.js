"use strict";
function cwImpacts(){
  const book=cwBook(),idx=cwIndexData(),changed=new Set(W.casework_changed_sources||[]);
  const byElement=new Map(), material=new Map();
  const changedUnits=[...idx.units.values()].filter(u=>changed.has(u.sid));
  for(const el of book.elements){
    const facts=book.facts.filter(f=>f.element===el.id);
    const prior=facts.filter(f=>!changed.has(f.anchor.source)||!cwCurrent(f.anchor));
    const wording=cwTerms(el.title).filter(w=>w.length>2);
    const topics=wording.filter(w=>cwWordSet(w).length>1);
    const specific=topics.filter(w=>!["notice","notification"].includes(w));
    const selected=specific.length?specific:topics.length?topics:wording;
    const refs=text=>[...text.toLowerCase().matchAll(/\b(?:shipment|invoice|order|account)\s+#?([a-z0-9][a-z0-9-]*)\b/g)].filter(m=>m[1].length===1||/[0-9-]/.test(m[1])).map(m=>m[0].replace(/\s+#?/," "));
    const expected=refs(el.title);
    const items=[];
    for(const u of changedUnits){
      const a=cwUnitAnchor(u), text=a.quote.toLowerCase();
      const revised=facts.find(f=>f.anchor.source===u.sid&&!cwCurrent(f.anchor)&&u.end>f.anchor.start&&u.start<f.anchor.end);
      const mentioned=expected.length?refs(text).filter(ref=>expected.some(x=>x.split(" ")[0]===ref.split(" ")[0])):[];
      if(!revised && (!selected.some(w=>cwContains(text,w)) ||
        (mentioned.length && !expected.some(ref=>mentioned.includes(ref)))))continue;
      const old=revised||prior.find(f=>f.role==="Support")||prior[0];
      items.push({id:u.id,old,fresh:a});
    }
    const stale=facts.filter(f=>!cwCurrent(f.anchor)&&!items.some(x=>x.old?.id===f.id));
    for(const f of stale)items.push({old:f});
    if(items.length){
      byElement.set(el.id,items);
      for(const f of facts)material.set(f.id,items);
    }
  }
  return {byElement,material};
}
function cwChangeView(){
  const impact=cwImpacts();
  return `<section class="card"><h3>Work affected by this production</h3>
    ${[...impact.byElement].map(([id,items])=>{
      const el=cwElement(id), facts=cwBook().facts.filter(f=>f.element===id);
      const outlines=cwBook().outlines.filter(o=>o.element===id);
      return cwRow(el.title,`<small>Proof chart · ${e(el.group)}</small>
      ${outlines.map(o=>`<p>Deposition question · ${e(o.witness)} · ${e(o.question)} ${btn("Inspect question","cw-inspect-outline",o.id)}</p>`).join("")}
      ${facts.filter(f=>f.approved||!cwCurrent(f.anchor)).map(f=>`<p>${f.role==="Contrary"?"Counsel review sheet":"Statement paragraph"} · ${e(f.wording)} ${cwCurrent(f.anchor)?btn(cwNeedsReview(f,items)?"Review this paragraph":"Reviewed for these sources","cw-review-fact",f.id):"· Needs a new citation"}</p>`).join("")}
      ${items.slice(0,12).map(item=>`<div class="cw-split"><div><h4>Earlier reviewed passage</h4><blockquote>${e(item.old?.anchor.quote||"No linked passage in earlier review")}</blockquote></div>
       <div><h4>Current passage to check</h4><blockquote>${e(item.fresh?.quote||"The original excerpt no longer resolves.")}</blockquote>${item.id?cwButton(item.id):""}</div></div>`).join("")}
       ${items.length>12?`<small>Showing 12 of ${items.length} candidate passages.</small>`:""}`);
    }).join("")||empty("No linked review work has a changed citation or a matching new record in this comparison.")}
    <small>New text is a candidate for review. Exact copies of an existing normalized source add no independent support.</small></section>`;
}
function cwCheckedVersions(items){
  return Object.fromEntries((items||[]).filter(x=>x.fresh).map(x=>[x.fresh.source,x.fresh.hash]));
}
function cwNeedsReview(item,items){
  return (items||[]).some(x=>x.fresh && item.checked_versions?.[x.fresh.source]!==x.fresh.hash);
}
function cwFactReady(f,impacts){
  return f.approved && f.role!=="Contrary" && cwCurrent(f.anchor) && !cwNeedsReview(f,impacts.get(f.id));
}
function cwOutlineNeedsReview(o,items){
  const statement=cwFact(o.statement), exhibit=cwFact(o.exhibit);
  return !statement || !exhibit || !cwCurrent(statement.anchor) || !cwCurrent(exhibit.anchor) ||
    statement.element!==o.element || exhibit.element!==o.element || !cwWitnessMatch(statement,o.witness) || cwNeedsReview(o,items);
}
function cwWorkProductView(){
  const facts=cwBook().facts, impacts=cwImpacts().material;
  return `<section class="card"><h3>Statement of facts</h3><p>Download reviewed wording with a numbered statement, pinpoint citations and an exhibit index. The separate counsel review sheet includes disputed wording, adverse passages and items needing review.</p>
    <div class="actions">${btn("Download statement of facts (.docx)","cw-statement","",!state.supportingOnly&&(facts.some(f=>cwFactReady(f,impacts))||eligibleBriefing().length)?"":"disabled")}
    ${btn("Download counsel review sheet (.docx)","cw-review-word","",state.supportingOnly?"disabled":"")}</div>
    ${facts.map(f=>cwRow(f.wording,`<small>${e(!cwCurrent(f.anchor)?"Earlier source version":cwNeedsReview(f,impacts.get(f.id))?"Recheck against new production":f.approved?"Reviewed wording":"Awaiting wording review")}</small>${cwButton(f.id)} ${cwCurrent(f.anchor)?btn("Review wording","cw-review-fact",f.id):""}`)).join("")}
    </section><details><summary>Counsel privilege log</summary><p>Open <code>case/privilege_log.html</code> inside the confidential run archive. Review descriptive metadata there and preview the fields before exporting.</p></details>`;
}
