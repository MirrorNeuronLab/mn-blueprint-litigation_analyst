/* Reading and graph presentation over the authorized frozen workspace. */
function money(value, currency) {
  if(value===null||value===undefined)return "Not established";
  const amount=/^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value));
  if(!amount)return `${e(currency)} ${e(value)}`;
  return `${e(currency)} ${amount[1]}${amount[2].replace(/\B(?=(\d{3})+(?!\d))/g,",")}.${(amount[3]||"").padEnd(2,"0")}`;
}

function readingFlags() {
  const count=(W.reading_review?.withheld_finding_ids||[]).length;
  if(!count)return "";
  return `<div class="review-notice"><span><strong>${count} finding${count===1?" needs":"s need"} review.</strong> Available records conflict with draft claims.</span>${btn("Review findings","view","Findings")}</div>`;
}
function flaggedFinding(id) {
  const finding=W.findings.find(f=>f.id===id), checks=(W.reading_review?.checks||[]).filter(check=>check.finding_id===id);
  const evidenceIds=[...new Set(checks.flatMap(check=>check.evidence_ids))];
  return `<article class="card flagged-finding ${state.finding===id?"selected":""}"><div class="section-title"><h3>${e(finding?.title||"Finding withheld during consistency review")}</h3>${pills("Needs correction")}</div><p>Available records conflict with this draft. It remains excluded from briefing exports.</p><div class="actions">${evidenceButtons(evidenceIds)}</div>${finding?`<details ${state.finding===id?'open':""}><summary>Original draft and review reason</summary><p>${e(finding.assessment)}</p><p class="qualification">${e(finding.limitations)}</p>${checks.map(check=>`<p>${e(check.reason)}</p>`).join("")}</details><div class="actions">${btn("Compare sources","compare-finding",id)}${btn("Missing information","finding-gaps",id)}</div>`:""}</article>`;
}
function findingsView() {
  const flags=W.reading_review?.withheld_finding_ids||[], visible=visibleFindings();
  const selected=visible.find(f=>f.id===state.finding);
  const pending=visible.filter(needsReview), completed=visible.filter(f=>!needsReview(f));
  if(selected)return `<h2>Findings</h2>${findingCard(selected,true)}`;
  if (!W.findings.length && !flags.length) {
    const questions = matchingIssues();
    return `<h2>Findings</h2><p class="brief-outcome">No finding cleared review.</p>
      ${questions.length ? `<h3>Questions examined</h3>${questions.map(q => `<article class="card"><h4>${e(reviewLabel(q.question))}</h4>
        <p class="muted">Investigator assessment · ${e(q.status)}</p>${btn("Review question and sources","issue",q.id)}</article>`).join("")}`
      : W.issues.length ? `<p>No examined questions match these filters.</p>${btn("Reset filters","reset")}`
      : `<p>Inspect the available records to continue the review.</p>${btn("Search evidence","view","Evidence Explorer")}`}`;
  }
  return `<h2>Findings</h2>${flags.length||pending.length?`<h3>Needs attention</h3>${flags.map(flaggedFinding).join("")}${pending.map(f=>findingCard(f)).join("")}`:
    visible.length ? "" : `${empty("No findings match these filters.")}${btn("Reset filters","reset")}`}
    ${completed.length?`<details ${!pending.length&&!flags.length?'open':""}><summary>Reviewed findings (${completed.length})</summary>${completed.map(f=>findingCard(f)).join("")}</details>`:""}`;
}
function reviewLabel(value) {
  return String(value||"").replace(/\bjob:[a-f0-9]{64}\b/g, id =>
    W.sources.find(source=>source.source_id===id)?.relative_path||"unresolved source reference");
}
function originalQuestion(value) {
  return reviewLabel(value)===value?"":`<details><summary>Original investigation question</summary><p>${e(value)}</p><p>Source references are investigation locators, not proof that records are missing.</p></details>`;
}
function matchingIssues() {
  if (!(state.query || state.address || state.from || state.to || state.sourceIds)) return W.issues;
  const sources = new Set(visibleSources().map(s => s.source_id));
  return W.issues.filter(q => q.supporting_evidence.concat(q.contradictory_evidence).some(id => sources.has(evidenceById.get(id)?.source_id)));
}
function compareCitations(ids) {
  const passages = ids.map(id => evidenceById.get(id)).filter(Boolean);
  const first = passages[0];
  const other = first && passages.find(p => p.content_sha256 !== first.content_sha256);
  return other ? btn("Compare cited records","compare-passages",JSON.stringify([first.evidence_id,other.evidence_id])) : "";
}
function gapCard(gap) {
  return `<div class="brief-followup"><h4>${e(reviewLabel(gap.question))}</h4>
    ${gap.requested_record ? `<p><strong>Record to check</strong> ${e(gap.requested_record)}</p>` : ""}
    ${gap.closure_condition ? `<p><strong>What would resolve it</strong> ${e(gap.closure_condition)}</p>` : ""}
    ${btn("View action draft","gap",gap.id)}</div>`;
}
function issueCard(issue) {
  const gaps = W.gaps.filter(gap => issue.gap_ids?.includes(gap.id));
  const contrary = issue.contradictory_evidence;
  const alternatives = issue.alternatives || [];
  const parent = issue.parent_id && W.issues.find(q => q.id === issue.parent_id);
  return `<article class="card brief-issue" id="issue-${e(issue.id)}" tabindex="-1">
    <h4>${e(reviewLabel(issue.question))}</h4><p class="muted">${e(issue.origin || "Investigation question")} · ${e(issue.status)}</p>
    ${parent ? `<p>Follow-up to ${e(reviewLabel(parent.question))}</p>` : ""}
    ${issue.assessment ? `<p><strong>Draft answer</strong> ${e(issue.assessment)}</p>` : ""}
    ${issue.supporting_evidence.length ? `<h5>Records considered</h5><div class="actions">${evidenceButtons(issue.supporting_evidence)}</div>` : ""}
    ${contrary.length ? `<h5>Contrary passages</h5><div class="actions">${evidenceButtons(contrary)}</div>` : ""}
    ${alternatives.length ? `<details><summary>Alternative explanations</summary><ul>${alternatives.map(a => `<li>${e(a)}</li>`).join("")}</ul></details>` : ""}
    ${gaps.map(gapCard).join("")}
    ${!gaps.length && issue.outstanding_enquiries?.length ? `<h5>Still open</h5><ul>${issue.outstanding_enquiries.map(q => `<li>${e(q)}</li>`).join("")}</ul>` : ""}
    ${originalQuestion(issue.question)}</article>`;
}
function coverageSources(key) {
  const ids=W.coverage?.[key];
  return Array.isArray(ids)?W.sources.filter(source=>ids.includes(source.source_id)).map(source=>source.source_id):null;
}
function analysisOverview() {
  const reasons={
    maximum_rounds_reached:"The configured investigation rounds were used. Some sources and questions remain unexamined.",
    planning_source_context_unavailable:"Analysis did not start: no complete source passage fit the planning context.",
    no_authorized_readable_sources:"Analysis did not start: no authorized readable sources were available.",
    investigation_deadline_reached:"The investigation reached its time limit. Some questions remain unexamined.",
    tool_call_budget_exhausted:"The investigation reached its tool limit. Some questions remain unexamined.",
    iteration_limit_exhausted:"The investigation reached its decision limit. Some questions remain unexamined.",
    cancelled:"The investigation was stopped before the review was complete."
  };
  const measures=[["readable_ids","Readable sources"],["assessor_source_ids","Sent for assessment"],
    ["reviewer_source_ids","Sent for independent review"],["unreadable_ids","Unreadable sources"]];
  return `<section class="card" aria-label="Review coverage"><h3>Review coverage</h3>
    ${reasons[W.analysis.stop_reason]?`<p>${e(reasons[W.analysis.stop_reason])}</p>`:""}
    <div class="coverage-grid">${measures.map(([key,label])=>{const ids=coverageSources(key);return `<div><span>${e(label)}</span>${ids?btn(`${ids.length} of ${W.sources.length}`,"coverage",key,`aria-label="${e(label)}: ${ids.length} of ${W.sources.length}"`):'<strong>Not recorded</strong>'}</div>`;}).join("")}</div>
    <p class="muted">Counts open the exact source list. Readable text and model review do not establish complete review or attorney approval.</p></section>`;
}
function supervisorReview() {
  const handoff=W.supervision, review=handoff?.next_review;
  if(!review)return "";
  if(review.finding_id) {
    const finding=W.findings.find(f=>f.id===review.finding_id);
    if(!finding||!needsReview(currentReview(finding)))return "";
  }
  const action=review.finding_id?btn("Review finding","finding",review.finding_id,'class="primary"'):
    review.gap_id?btn("Review evidence gap","gap",review.gap_id,'class="primary"'):
    review.kind==="consistency"?btn("Review flagged findings","view","Findings",'class="primary"'):
    btn("Review questions","view","Issues & evidence",'class="primary"');
  const gap = W.gaps.find(g => g.id === review.gap_id);
  return `<section class="card brief-next" aria-label="Your next review"><span class="eyebrow">Your next review</span><h3>${e(reviewLabel(review.question))}</h3>
    <p>${gap?.requested_record ? `<strong>Record to check</strong> ${e(gap.requested_record)}` : e(review.reason)}</p>
    <div class="actions">${action}${compareCitations(review.evidence_ids)}</div>
    <details><summary>Review basis and timing</summary>${gap?.closure_condition ? `<p><strong>What would resolve it</strong> ${e(gap.closure_condition)}</p>` : ""}
    <p>${e(review.timing)}</p>${review.evidence_ids.length ? evidenceButtons(review.evidence_ids) : ""}<p>${e(handoff.boundary)}</p></details>
    ${originalQuestion(review.question)}</section>`;
}
function transactionSummary(financial) {
  const first = financial.transactions[0];
  if (!first) return "";
  const records = financial.events.filter(r => r.transaction_ref === first.transaction_ref && r.currency === first.currency && r.ledger_id === first.ledger_id);
  const labels = {requested:"Requested", approved:"Stated approval", net_balance:"Recorded net"};
  const amounts = records.filter(r => labels[r.event_type]).slice(0, 6);
  return `<section class="card record-summary"><div class="section-title"><h3>Transaction summary · ${e(first.transaction_ref)}</h3>${btn("View timeline","view","Chronology")}</div>
    ${amounts.length ? `<div class="record-amounts">${amounts.map(r => `<div><span>${labels[r.event_type]}</span><strong>${money(r.amount,r.currency)}</strong>${evidenceButtons(r.evidence_ids)}</div>`).join("")}</div>` : ""}
    <p class="summary-result">Request less stated approval <strong>${money(first.request_minus_approval,first.currency)}</strong></p>
    <p class="summary-result">Posting / reversal net <strong>${money(first.posting_reversal_net,first.currency)}</strong></p><p>${e(first.qualification)}</p>
    <details><summary>Record classifications and scope</summary><p>Counsel supplied the classifications and ledger grouping.</p>
    ${financial.transactions.length > 1 ? btn(`View all ${financial.transactions.length} transaction groups`,"view","Chronology") : ""}</details></section>`;
}
function passageHighlights() {
  const items = W.case_brief?.highlights || [];
  if (!items.length) return "";
  return `<section class="brief-exhibits"><h3>What the records say</h3><div class="exhibit-grid">${items.map(item => {
    const passage = evidenceById.get(item.evidence_id), source = sourceById.get(passage.source_id);
    const date = recordDate(source);
    return `<figure class="card exhibit"><figcaption><span class="eyebrow">${e(documentType(source))} excerpt${date ? ` · <span title="${e(date.basis)}">${e(date.value)}</span>` : ""}</span>
      <h4>${e(documentTitle(source))}</h4></figcaption>${item.excerpt ? `<blockquote>${e(item.excerpt)}</blockquote>` : ""}
      <div>${btn("Read passage","evidence",item.evidence_id,`title="${e(source.relative_path)}"`)}</div></figure>`;
  }).join("")}</div></section>`;
}
function readingOverview() {
  const retained = W.findings.map(currentReview).filter(f => !["Needs correction","Dismissed"].includes(f.review_state));
  const count = W.issues.length, cited = W.case_brief?.cited_ids.length || 0;
  const handoff = supervisorReview();
  const notStarted = ["no_authorized_readable_sources","planning_source_context_unavailable"].includes(W.analysis.stop_reason);
  const status = notStarted ? "Analysis did not start" : W.analysis.status;
  const noResults = !retained.length && !count && !cited && !W.financial_review.events.length;
  const synthetic = W.sample || W.sources.some(s => s.text?.includes("SYNTHETIC TEST MATTER"));
  const findingCount = retained.length === 1 ? "1 finding" : `${retained.length} findings`;
  const outcome = [count ? `${count} question${count === 1 ? "" : "s"} examined` : "",
    cited ? `${cited} cited passage${cited === 1 ? "" : "s"}` : "",
    retained.length ? findingCount + " available for review" : W.findings.length ? "No current finding in the brief" : "No finding cleared review"].filter(Boolean).join(" · ");
  return `<div class="page-intro brief-heading"><div><p class="eyebrow">${synthetic ? "Synthetic test matter · " : ""}${e(status)}</p>
    <h2>Case summary</h2><p class="brief-outcome">${e(outcome)}</p></div>${handoff ? btn("Read case brief","read-brief") : primaryAction()}</div>
    ${retained.length ? `<section class="brief-findings"><h3>Key findings</h3>${retained.slice(0,2).map(f => {
      const reviewed = ["Reviewed with qualification","Revised"].includes(f.review_state);
      return `<article class="card"><span class="eyebrow">${e(f.review_state)}</span><h4>${e(f.title)}</h4>
        <p>${e(reviewed && f.reviewed_text ? f.reviewed_text : f.assessment)}</p><p class="muted">${e(f.limitations)}</p>
        ${btn("View finding","finding",f.id)}</article>`;
    }).join("")}</section>` : ""}
    ${transactionSummary(W.financial_review)}${passageHighlights()}
    ${noResults ? `<section class="card"><h3>Review progress and next steps</h3><p>No draft findings were retained. This does not establish that no relevant events occurred.</p>${btn("Search evidence","view","Evidence Explorer")}</section>` : ""}
    ${handoff}${handoff && W.supervision.next_review.kind === "consistency" ? "" : readingFlags()}
    <div class="overview-counts" aria-label="Matter records">${btn(`${W.sources.length} document${W.sources.length === 1 ? "" : "s"}`,"sources")}${W.package_mode !== "approved_excerpt_briefing" ? btn("Explore case graph","view","Case graph") : ""}${W.gaps.length ? btn(`${W.gaps.length} open evidence gap${W.gaps.length === 1 ? "" : "s"}`,"view","Issues & evidence") : ""}</div>
    ${analysisOverview()}
    <details><summary>Review objective and scope</summary><p>${e(W.matter_scope?.intended_decision || W.goal)}</p><p>${e(W.analysis.scope)}</p>
      ${reviewAllowance()}<p>Snapshot ${e(W.snapshot_id)}</p>${W.reading_copy ? `<p>${e(W.reading_copy.definition)}</p>` : ""}</details>`;
}
function markdownInline(value) {
  return e(value).replace(/\[([^\]\n]+)\]\((?:evidence:|exact-source-passages\.md#)([a-zA-Z0-9-]+)\)/g,(_,label,id)=>
    evidenceById.has(id)?`<button class="citation-link" data-action="evidence" data-id="${id}">${label} ↗</button>`:label)
    .replace(/`([^`]+)`/g,"<code>$1</code>").replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>")
    .replace(/\\([|_\[\]()*`])/g,"$1");
}
function markdownRows(line) {
  return line.trim().replace(/^\||\|$/g,"").split(/(?<!\\)\|/).map(s=>s.trim());
}
function renderMarkdown(text) {
  const lines=String(text).replace(/\r\n/g,"\n").split("\n"), blocks=[];
  let i=0, heading=0;
  while(i<lines.length) {
    const line=lines[i];
    if(!line.trim()){i++;continue;}
    if(line.startsWith("```")) {
      const code=[];i++;while(i<lines.length&&!lines[i].startsWith("```"))code.push(lines[i++]);i++;
      blocks.push(`<pre><code>${e(code.join("\n"))}</code></pre>`);continue;
    }
    const title=/^(#{1,6})\s+(.+)$/.exec(line);
    if(title){const level=Math.min(6,title[1].length+1);blocks.push(`<h${level} id="report-heading-${heading++}">${markdownInline(title[2])}</h${level}>`);i++;continue;}
    if(line.startsWith("|")&&lines[i+1]&&/^\|[\s:|\-]+\|$/.test(lines[i+1])) {
      const headers=markdownRows(line), rows=[];i+=2;
      while(i<lines.length&&lines[i].startsWith("|"))rows.push(markdownRows(lines[i++]).map(markdownInline));
      blocks.push(table(headers,rows));continue;
    }
    if(/^>\s?/.test(line)){const quote=[];while(i<lines.length&&/^>\s?/.test(lines[i]))quote.push(lines[i++].replace(/^>\s?/,""));blocks.push(`<blockquote>${e(quote.join("\n"))}</blockquote>`);continue;}
    if(/^(?:[-*]|\d+\.)\s/.test(line)){const ordered=/^\d+\./.test(line),items=[];while(i<lines.length&&(ordered?/^\d+\.\s/:/^[-*]\s/).test(lines[i]))items.push(`<li>${markdownInline(lines[i++].replace(/^(?:[-*]|\d+\.)\s/,""))}</li>`);blocks.push(`<${ordered?"ol":"ul"}>${items.join("")}</${ordered?"ol":"ul"}>`);continue;}
    blocks.push(`<p>${markdownInline(line)}</p>`);i++;
  }
  return blocks.join("\n");
}
function passageRegister() {
  const term = (state.passageQuery || "").toLocaleLowerCase();
  const ids = new Set([...(W.case_brief?.cited_ids || []), ...W.evidence.map(p => p.evidence_id)]);
  const entries = Array.from(ids,(id,i) => ({passage:evidenceById.get(id), number:i+1}));
  const matches = term ? entries.filter(({passage:p}) => {
    const source = sourceById.get(p.source_id);
    return [p.text, documentTitle(source), source.relative_path, p.evidence_id].some(value => value.toLocaleLowerCase().includes(term));
  }) : entries;
  const page = pageOf(matches,state.passagePage,12);
  return `<section class="report-paper"><h3>Exact source passages</h3><form class="document-search" id="passage-search" role="search">
    <label>Search passages<input type="search" id="passage-query" value="${e(state.passageQuery)}" placeholder="Search quotation or document"></label>
    <button type="submit">Search</button></form><p class="muted">${matches.length} matching passages</p>
    ${page.items.map(({passage:p, number}) => `<article class="passage-entry"><h4>${e(documentTitle(sourceById.get(p.source_id)))}</h4>
      <p class="muted">Passage ${number} · Characters ${e(p.start_offset)}–${e(p.end_offset)}</p><blockquote>${e(p.text)}</blockquote>
      ${btn("Read passage","evidence",p.evidence_id)}</article>`).join("")}
    ${pageControls(page,"passage-page","passages")}</section>`;
}
function briefReader(markdown) {
  const headings = [...markdown.matchAll(/^(#{1,6})\s+(.+)$/gm)];
  const options = headings.map(([_,level,title],index) => level === "##" ?
    `<option value="${index}">${e(title)}</option>` : "").join("");
  return `<div class="brief-reader">${options ? `<label class="section-jump">Jump to section<select id="report-section">
    <option value="">Choose a section</option>${options}</select></label>` : ""}
    <article class="report-paper markdown">${renderMarkdown(markdown)}</article></div>`;
}
function reportsView() {
  const reports=W.reading_reports||[], selected=reports.find(r=>r.id===state.reportId)||reports[0];

  if(!selected)return `<h2>Reports</h2>${reportTabs()}${briefingReadiness()}${empty("Reading reports are not included in this package.")}`;
  return `<h2>Reports</h2>${reportTabs()}<p class="muted">Reports cover the full authorized matter. Download a copy from Actions.</p>
    <div class="report-tabs">${reports.map(r=>btn(r.title,"select-report",r.id,r.id===selected.id?'aria-pressed="true"':"" )).join("")}</div>
    ${selected.id === "source-passages" ? passageRegister() : briefReader(selected.markdown)}
    <details><summary>Briefing eligibility</summary>${briefingReadiness()}</details>`;
}

function peopleView() {
  return (W.casework ? peopleTabs() : "") + sourceGraphView();
}
function peopleTabs() {
  return routeTabs([["Source relationships","People & relationships"],["Witness preparation","Witness preparation"],["Identities","Identity review"]]);
}
function readingChronology() {
  const sources=new Set(visibleSources().map(s=>s.source_id));
  const events=W.case_map.nodes.filter(n=>["communication","financial_record"].includes(n.kind)&&n.source_ids.some(id=>sources.has(id))).filter(n=>{const day=n.date?.slice(0,10);return (!state.from&&!state.to)||day&&(!state.from||day>=state.from)&&(!state.to||day<=state.to);}).sort((a,b)=>(a.date||"9999").localeCompare(b.date||"9999"));
  return `<div class="page-intro"><div><h2>Timeline</h2><p>Email dates and counsel-labelled financial events. Undated records stay unresolved; financial dates retain their annotation basis.</p></div>${btn("Open case graph","view","Case graph")}</div><div class="timeline reading-timeline">${events.map(n=>`<article><span class="eyebrow">${e(n.date?.slice(0,10)||"Date unresolved")} · ${n.kind==="communication"?"Communication":"Financial record"}</span><h3>${e(n.label)}</h3><small>${e(n.date_label)}</small><p>${e(n.qualification)}</p>${evidenceButtons(n.evidence_ids)}</article>`).join("")||empty("No event records match this scope.")}</div><details><summary>Inspect transaction arithmetic</summary>${transactionReview()}</details>`;
}
document.addEventListener("click",event=>{
  const button=event.target.closest("[data-action]");if(!button)return;
  const {action,id}=button.dataset;
  if(action==="coverage") {
    const ids=coverageSources(id);
    if(ids)goto({view:"Evidence Explorer",sourceIds:ids,query:"",address:"",from:"",to:"",source:null,citedOnly:false,documentPage:0});
  }
  else if(action==="select-report")goto({reportId:id});
  else if(action==="read-brief")goto({view:"Reports",reportId:"counsel-brief",source:null});
  else if(action==="download-report"){const report=W.reading_reports?.find(r=>r.id===id);if(report)download(report.filename,report.markdown,"text/markdown");}
  else if(action==="reading-task"){
    const task=W.reading_tasks.find(t=>t.id===id);if(!task)return;
    const content=`${pills(task.status)}<p><strong>Record:</strong> ${e(task.record)}</p><p><strong>Decision it informs:</strong> ${e(task.purpose)}</p><p><strong>Closure test:</strong> ${e(task.closure)}</p><p>Owner: ${e(task.owner)}</p><p class="muted">${e(task.origin)}</p><div class="actions">${evidenceButtons(task.evidence_ids)}</div>`;
    reportUI.openInspector(task.title,content,button);
  }
});
document.addEventListener("change",event=>{
  if(event.target.id !== "report-section" || !event.target.value) return;
  const heading = document.getElementById(`report-heading-${event.target.value}`);
  if(heading) {
    heading.tabIndex = -1;
    heading.focus({preventScroll:true});
    heading.scrollIntoView({block:"start"});
  }
  event.target.value = "";
});
