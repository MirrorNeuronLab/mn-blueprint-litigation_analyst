"use strict";
const cwStop=new Set("what which who whom whose where when shows show me evidence documents document records record passages passage has have had do does did is was are were has the a an any of on for those these them only ones that this our customer address addresses about before after prior to predate predates earlier later than support supports contradicts contradict identify there and can i see find establish establishes whether list search were element elements proof facts fact claim defense against same".split(" "));
function cwTerms(text){
  return [...new Set((text.toLowerCase().match(/[\p{L}\p{N}@._-]+/gu)||[]).map(t=>t.replace(/^[._-]+|[._-]+$/g,"")).filter(t=>t&&!cwStop.has(t)))];
}
function cwWordSet(word){
  if(/^(recei(pt|v)|acknowledg|deliver)/.test(word))return ["receipt","receiv","acknowledg","deliver"];
  if(/^(sent|send|dispatch|mail(?:ed|ing)?$)/.test(word))return ["sent","send","dispatch","mailed"];
  if(/^(terminat|cancel)/.test(word))return ["terminat","cancel"];
  if(/^(testimony|testif|deposition)/.test(word))return ["testimony","testif","deposition"];
  if(/^(notic|notification)/.test(word))return ["notice","notification"];
  return [word];
}
function cwContains(text,word){return cwWordSet(word).some(w=>text.includes(w));}
function cwCutoff(label){
  if(/^\d{4}-\d{2}-\d{2}$/.test(label)){
    const d=new Date(label+"T00:00:00Z");
    return !isNaN(d)&&d.toISOString().startsWith(label)?{day:label}:{error:"Enter a valid calendar date."};
  }
  const candidates=new Map();
  for(const row of W.case_query_index.dates)if(row.meaning.toLowerCase()===label&&row.earliest&&row.earliest===row.latest)
    candidates.set(row.earliest,row.unit_id);
  for(const ev of cwBook().events)if((ev.meaning.toLowerCase()===label||ev.label.toLowerCase()===label) &&
    ev.from && ev.from===ev.to && cwCurrent(cwFact(ev.fact)?.anchor||{}))candidates.set(ev.from,ev.fact);
  if(candidates.size!==1)return {error:candidates.size?`Several dates match ${label}: ${[...candidates.keys()].join(", ")}. Enter the intended cutoff date.`:`A single exact date for “${label}” is unresolved. Enter a cutoff in YYYY-MM-DD format.`};
  const [day,id]=[...candidates][0];return {day,id};
}
function cwParseQuestion(question,prior){
  const cleaned=question.trim().replace(/[?!.]+$/,"");
  const follow=/\b(those|these|them|only|of the same)\b/i.test(cleaned);
  const comparison=/\b(before|predates?|prior to|earlier than|after|later than)\s+(?:the\s+)?(.+)$/i.exec(cleaned);
  if(follow&&!prior)return {error:"Ask for a set of records before narrowing it."};
  const subject=(comparison?cleaned.slice(0,comparison.index):cleaned)
    .replace(/^who (?:sent|was addressed (?:on|in)|received)\s+/i,"")
    .replace(/\b(?:contrary to|opposes?|corroborates?)\b/gi," ");
  let terms=cwTerms(subject);
  if(follow && prior)terms=Array.from(new Set([...prior.terms,...terms]));
  let role=/(contradict|contrary|against|oppos)/i.test(cleaned)?"Contrary":/\b(supports?|corroborat\w*)\b/i.test(cleaned)?"Support":prior&&follow?prior.role:"";
  const relation=/\bwho (?:sent|was addressed|received)\b/i.test(cleaned)?(/who sent/i.test(cleaned)?["FROM_HEADER"]:["TO_HEADER","CC_HEADER","BCC_HEADER"]):null;
  if(!comparison&&!follow&&!/^(which|what|who|show|find|list|identify|search|records|evidence)\b/i.test(cleaned))
    return {error:"Ask which records address a topic, what supports or contradicts an element, or who sent a named message."};
  if(!terms.length&&!follow)return {error:"Name an issue, witness, document, or transaction to search."};
  let bounds=follow?[...(prior?.bounds||[])]:[];
  if(comparison){
    const label=comparison[2].toLowerCase().replace(/\s+(?:occurred|happened)$/,"").trim(),cut=cwCutoff(label);
    if(cut.error)return cut;
    bounds.push({dir:/^(after|later)/i.test(comparison[1])?"after":"before",...cut,label});
  }
  return {terms,bounds,role,relations:relation||(follow?prior.relations:null)};
}
function cwRecordDates(idx){
  const confirmed=new Map(), windows=new Map();
  for(const event of cwBook().events){
    const f=cwFact(event.fact);
    if(event.meaning!=="Record date"||!event.from||!event.to||!f||!cwCurrent(f.anchor))continue;
    if(!confirmed.has(f.anchor.source))confirmed.set(f.anchor.source,[]);
    confirmed.get(f.anchor.source).push({earliest:event.from,latest:event.to});
  }
  for(const [sid,rows] of new Map([...idx.sourceDates,...confirmed])){
    const known=rows.filter(d=>d.earliest&&d.latest);
    if(known.length)windows.set(sid,[known.map(d=>d.earliest).sort()[0],known.map(d=>d.latest).sort().at(-1)]);
  }
  return windows;
}
function cwSearch(plan){
  const idx=cwIndexData(),matches=[],unknown=new Set(), grouped=new Map(), factsBySource=new Map();
  for(const f of cwBook().facts)if(cwCurrent(f.anchor)){
    const list=factsBySource.get(f.anchor.source)||[];list.push(f);factsBySource.set(f.anchor.source,list);
  }
  const windows=cwRecordDates(idx);
  const aliases=cwAliases(), namedFile=plan.terms.some(t=>/\.[a-z0-9]{2,5}$/i.test(t));
  for(const unit of idx.units.values()){
    const source=sourceById.get(unit.sid), anchor=cwUnitAnchor(unit);
    const overlaps=(a,b)=>a<unit.end&&b>unit.start;
    const facts=(factsBySource.get(unit.sid)||[]).filter(f=>overlaps(f.anchor.start,f.anchor.end));
    const links=(idx.linksBySource.get(unit.sid)||[]).filter(l=>{
      const p=evidenceById.get(l.passage_id);return p&&!["QUOTES","SUPPORTED_BY_FACT","CONTESTED_BY_FACT","CONTEXT_FACT","CONFIRMED_ALIAS_OF"].includes(l.relation)&&overlaps(p.start_offset,p.end_offset);
    });
    const roles=new Set(facts.map(f=>f.role));
    for(const l of links){
      if(["CITES_IN_SUPPORT","SUPPORTED_BY_FACT"].includes(l.relation))roles.add("Support");
      if(["CITES_IN_CONFLICT","CONTESTED_BY_FACT"].includes(l.relation))roles.add("Contrary");
    }
    if(plan.role&&!roles.has(plan.role))continue;
    if(plan.relations && !links.some(l=>plan.relations.includes(l.relation)))continue;
    const terms=[anchor.quote,namedFile?source.relative_path:"",...facts.flatMap(f=>[f.wording,f.witness,cwElement(f.element)?.title||""]),
      ...links.flatMap(l=>[l.origin,l.target])].join(" ").toLowerCase();
    const names=aliases.flatMap(a=>cwMentions(terms,a.alias)?[a.person]:cwMentions(terms,a.person)?[a.alias]:[]).join(" ").toLowerCase();
    if(!plan.terms.every(term=>cwContains(terms+" "+names,term)))continue;
    const window=windows.get(unit.sid);
    if(plan.bounds.length && (!window || plan.bounds.some(b=>window[0]<b.day&&window[1]>=b.day || window[0]<=b.day&&window[1]>b.day))){
      unknown.add(unit.sid);continue;
    }
    if(plan.bounds.some(b=>b.dir==="before"?window[1]>=b.day:window[0]<=b.day))continue;
    const key=`${source.content_sha256}:${unit.start}:${unit.end}`;
    if(grouped.has(key)){
      const first=grouped.get(key);
      first.copies.add(unit.sid);
      first.roles=[...new Set([...first.roles,...roles])];
      first.proofRoles=[...new Set([...first.proofRoles,...facts.map(f=>f.role)])];
      first.links.push(...links.filter(l=>!first.links.includes(l)));
      continue;
    }
    const row={id:unit.id,sid:unit.sid,quote:anchor.quote,window,copies:new Set([unit.sid]),roles:[...roles],
      proofRoles:facts.map(f=>f.role),links:links.filter(l=>!plan.relations||plan.relations.includes(l.relation))};
    matches.push(row);grouped.set(key,row);
  }
  return {matches,unknown:[...unknown],plan};
}
function cwAnswerSummary(result){
  const sources=new Set(result.matches.map(r=>sourceById.get(r.sid).content_sha256));
  const supported=new Set(result.matches.filter(r=>r.proofRoles.includes("Support")).map(r=>sourceById.get(r.sid).content_sha256));
  const contrary=new Set(result.matches.filter(r=>r.proofRoles.includes("Contrary")).map(r=>sourceById.get(r.sid).content_sha256));
  return `<p>${sources.size} distinct matching source versions. Counsel linked ${supported.size} as supporting and ${contrary.size} as contrary for the matching passages.</p>`;
}
function cwRunChain(chain){
  let plan=null;
  for(const q of chain){
    plan=cwParseQuestion(q,plan);
    if(plan.error)return plan;
  }
  return cwSearch(plan);
}
function cwQueryView(){
  const index=W.case_query_index;
  if(!index)return empty("This snapshot has no offline case question index.");
  const result=cwAnswer, plan=result?.plan;
  const output=!result?"":result.error?empty(result.error):
    `<h3>${result.matches.length} distinct matching passage${result.matches.length===1?"":"s"}</h3>${cwAnswerSummary(result)}
    <p>Search terms: ${e(plan.terms.join(", "))}. ${plan.role?e(plan.role+" links only."):""} ${plan.bounds.map(b=>e(b.dir+" "+b.day+" ("+b.label+")")+(b.id?" "+cwButton(b.id,"Open cutoff source"):"")).join(" ")}
    ${result.unknown.length?e(result.unknown.length+" sources have unknown or overlapping record dates."):""}</p>
    ${result.matches.slice(0,60).map(r=>cwRow(sourceById.get(r.sid).relative_path,
      `<blockquote>${e(r.quote)}</blockquote><small>${e(r.window?r.window.join(" to "):"Record date unresolved")} · ${r.copies.size} source cop${r.copies.size===1?"y":"ies"} · ${e(r.roles.join(", ")||"Matching source text")}</small>${r.links.slice(0,3).map(l=>`<small>${e(l.origin)} → ${e(l.relation)} → ${e(l.target)}</small>`).join("")}${cwButton(r.id)}${r.copies.size>1?`<details><summary>Inspect matching copies</summary>${[...r.copies].map(sid=>btn(sourceById.get(sid).relative_path,"source",sid)).join(" ")}</details>`:""}`)).join("")}
    ${result.matches.length>60?"<p>First 60 matching passages shown. Narrow the question to inspect a smaller set.</p>":""}
    ${!result.matches.length?empty("No matching passage within this search. Check the coverage and unresolved dates."):""}
    ${btn("Save question","cw-save-query")} ${result.matches.length?btn("Show matching records on graph","cw-answer-graph"):""}`;
  return `<section class="cw-section"><h2>Ask the case graph</h2>${routeTabs(cwRoutes)}
    <form id="cw-question" class="cw-form"><label>Question about this matter<input name="question" required maxlength="500" placeholder="Which records address receipt?"></label><div><button>Ask question</button> ${cwConversation.length?btn("Start new question","cw-new-query"):""}</div></form>
    ${cwConversation.map(q=>`<p><strong>${e(q)}</strong></p>`).join("")}${output}
    <details><summary>Search coverage</summary><p>${index.units.length} of ${index.total_units} authorized text passages and ${index.links.length} of ${index.total_links} cited graph links. Snapshot ${e(index.snapshot)}. Matches identify language and recorded relationships. Read the passage to determine what it establishes. Dates filter the document or testimony date.</p></details>
    ${cwBook().queries.length?'<h3>Saved questions</h3>'+cwBook().queries.map(q=>btn(q.chain.join(" → "),"cw-rerun-query",q.id)).join(" "):""}</section>`;
}
