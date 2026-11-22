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
  return `<h2>Findings</h2>${flags.length||pending.length?`<h3>Needs attention</h3>${flags.map(flaggedFinding).join("")}${pending.map(f=>findingCard(f)).join("")}`:
    empty(visible.length?"No findings need review in this view.":"No findings match this view.")}
    ${completed.length?`<details ${!pending.length&&!flags.length?'open':""}><summary>Reviewed findings (${completed.length})</summary>${completed.map(f=>findingCard(f)).join("")}</details>`:""}`;
}
function reviewLabel(value) {
  return String(value||"").replace(/\bjob:[a-f0-9]{64}\b/g, id =>
    W.sources.find(source=>source.source_id===id)?.relative_path||"unresolved source reference");
}
function originalQuestion(value) {
  return reviewLabel(value)===value?"":`<details><summary>Original investigation question</summary><p>${e(value)}</p><p>Source references are investigation locators, not proof that records are missing.</p></details>`;
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
  return `<section class="card" aria-label="Review coverage"><div class="section-title"><h3>${e(W.analysis.status)}</h3>${btn("Read detailed reports","view","Reports")}</div>
    ${reasons[W.analysis.stop_reason]?`<p>${e(reasons[W.analysis.stop_reason])}</p>`:""}
    <div class="coverage-grid">${measures.map(([key,label])=>{const ids=coverageSources(key);return `<div><span>${e(label)}</span>${ids?btn(`${ids.length} of ${W.sources.length}`,"coverage",key,`aria-label="${e(label)}: ${ids.length} of ${W.sources.length}"`):'<strong>Not recorded</strong>'}</div>`;}).join("")}</div>
    <p class="muted">Counts open the exact source list. Readable text and model review do not establish complete review or attorney approval.</p></section>`;
}
function gapSteps(limit=3) {
  return W.gaps.slice(0,limit).map(g=>`<div class="next-item"><div>${btn(reviewLabel(g.question),"gap",g.id)}<p>${e(g.why_it_matters||g.priority_basis)}</p><small>Done when: ${e(g.closure_condition||"Record a source-backed answer or a reviewed limitation.")}</small></div></div>`).join("");
}
function supervisorReview() {
  const handoff=W.supervision, review=handoff?.next_review;
  if(!review)return "";
  if(review.finding_id) {
    const finding=W.findings.find(f=>f.id===review.finding_id);
    if(!finding||!needsReview(currentReview(finding)))return "";
  }
  const action=review.finding_id?btn("Review finding","finding",review.finding_id,'class="primary"'):
    review.gap_id?btn("Review evidence gap","gap",review.gap_id,'class="primary"'):btn("Review questions","view","Issues & evidence",'class="primary"');
  const passages = review.evidence_ids.map(id => evidenceById.get(id)).filter(Boolean);
  const sourceCount = new Set(passages.map(p => p.source_id)).size;
  const basis = passages.length ? `<p class="muted">Review basis: ${passages.length} cited ${passages.length === 1 ? "passage" : "passages"} from ${sourceCount} source ${sourceCount === 1 ? "record" : "records"}.</p>` : "";
  return `<section class="card" aria-label="Your next review"><span class="eyebrow">Your next review</span><h3>${e(reviewLabel(review.question))}</h3>
    <p>${e(review.reason)}</p><p class="muted">${e(review.timing)}</p>${basis}<div class="actions">${action}${review.evidence_ids.length?evidenceButtons(review.evidence_ids):""}</div>
    ${originalQuestion(review.question)}
    <details><summary>How to record your decision</summary><p>${e(handoff.boundary)}</p></details></section>`;
}
function readingOverview() {
  const financial=W.financial_review, first=financial.transactions[0];
  const records=financial.events.filter(r=>!first||(r.transaction_ref===first.transaction_ref&&r.currency===first.currency&&r.ledger_id===first.ledger_id));
  const synthetic=W.sample||W.sources.some(s=>s.text?.includes("SYNTHETIC TEST MATTER"));
  const retained=visibleFindings();
  const handoff=supervisorReview();
  return `<div class="page-intro"><div><h2>${retained.length||records.length?"What the records support":"Review progress and next steps"}</h2><p>${e(W.matter_scope?.intended_decision||W.goal)}</p></div>${handoff?"":primaryAction()}</div>
    ${synthetic?'<p class="sample-label">Synthetic test matter</p>':""}
    ${handoff}
    ${W.case_map ? caseMapView(true) : ""}
    ${analysisOverview()}
    <div class="reading-grid overview-main"><section class="card record-summary"><div class="section-title"><div><span class="eyebrow">Recorded facts</span><h3>${e(first?.transaction_ref||"Current findings")}</h3></div>${btn("View timeline","view","Chronology")}</div>
      ${records.length?`<div class="record-amounts">${records.filter(r=>["requested","approved","net_balance"].includes(r.event_type)).slice(0,6).map(r=>`<div><span>${e(({requested:"Requested",approved:"Stated approval",net_balance:"Recorded net"})[r.event_type])}</span><strong>${money(r.amount,r.currency)}</strong>${evidenceButtons(r.evidence_ids)}</div>`).join("")}</div>`:
        retained.length?retained.slice(0,2).map(f=>`<h4>${e(f.title)}</h4><p>${e(currentReview(f).reviewed_text||f.assessment)}</p>${btn("View finding","finding",f.id)}`).join(""):`<p><strong>No draft findings were retained.</strong></p><p>This does not establish that no relevant events occurred. Inspect the saved sources and unresolved questions before drawing a conclusion.</p>${btn("Search evidence","view","Evidence Explorer")}`}
      ${first?`<p class="summary-result">Request less stated approval <strong>${money(first.request_minus_approval,first.currency)}</strong></p><p class="summary-result">Posting / reversal net <strong>${money(first.posting_reversal_net,first.currency)}</strong></p><p class="qualification">${e(first.qualification)}</p><details><summary>Record classifications and scope</summary><p>Event types and ledger grouping are counsel annotations. Exact quotations and recorded amounts are verified.</p>${financial.transactions.length>1?`<p>${financial.transactions.length} transaction groups are available. This summary shows ${e(first.transaction_ref)}.</p>${btn("View all transaction records","view","Chronology")}`:""}</details>`:""}</section>
      <section class="card"><span class="eyebrow">Next useful work</span><h3>What remains unresolved</h3>${nextSteps(3)||gapSteps()||empty("No structured next steps were supplied. Choose a specific question after inspecting the saved sources.")}${btn("View questions","view","Issues & evidence")}</section></div>
    ${handoff&&W.supervision.next_review.kind==="consistency"?"":readingFlags()}
    <div class="overview-counts" aria-label="Investigation counts">${btn(`${W.sources.length} documents`,"sources")}${btn(`${W.temporal.nodes.length} correspondents`,"view","People & relationships")}${btn(`${W.gaps.length} evidence gaps`,"view","Issues & evidence")}</div>
    <section class="card"><h3>Review scope</h3><p>${e(W.analysis.scope)}.</p><details><summary>Coverage and provenance</summary><p>${W.coverage.readable_ids.length} readable documents. ${retained.length} narrative draft findings remain available after record checks.</p>${reviewAllowance()}<p>Snapshot ${e(W.snapshot_id)}</p>${W.reading_copy?`<p>${e(W.reading_copy.definition)}</p>`:""}</details></section>`;
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
    if(/^>\s?/.test(line)){const quote=[];while(i<lines.length&&/^>\s?/.test(lines[i]))quote.push(lines[i++].replace(/^>\s?/,""));blocks.push(`<blockquote>${quote.map(markdownInline).join("\n")}</blockquote>`);continue;}
    if(/^(?:[-*]|\d+\.)\s/.test(line)){const ordered=/^\d+\./.test(line),items=[];while(i<lines.length&&(ordered?/^\d+\.\s/:/^[-*]\s/).test(lines[i]))items.push(`<li>${markdownInline(lines[i++].replace(/^(?:[-*]|\d+\.)\s/,""))}</li>`);blocks.push(`<${ordered?"ol":"ul"}>${items.join("")}</${ordered?"ol":"ul"}>`);continue;}
    blocks.push(`<p>${markdownInline(line)}</p>`);i++;
  }
  return blocks.join("\n");
}
function reportsView() {
  const reports=W.reading_reports||[], selected=reports.find(r=>r.id===state.reportId)||reports[0];

  if(!selected)return `<h2>Reports</h2>${reportTabs()}${briefingReadiness()}${empty("Reading reports are not included in this package.")}`;
  const headings=[...selected.markdown.matchAll(/^#{1,6}\s+(.+)$/gm)];
  return `<h2>Reports</h2>${reportTabs()}${briefingReadiness()}<p class="muted">Reports cover the full authorized snapshot. Use Actions to download Markdown or save a copy.</p>
    <div class="report-tabs">${reports.map(r=>btn(r.title,"select-report",r.id,r.id===selected.id?'aria-pressed="true"':"" )).join("")}</div>
    <div class="report-layout"><aside class="report-toc"><strong>In this report</strong>${headings.map((h,i)=>btn(h[1],"report-heading",String(i))).join("")}</aside><article class="report-paper markdown">${renderMarkdown(selected.markdown)}</article></div>`;
}

function graphView() {
  const switcher=`<div class="report-tabs">${btn("Case graph","graph-mode","case",state.graphMode!=="sources"?'aria-pressed="true"':"")}${btn("Advanced source relationships","graph-mode","sources",state.graphMode==="sources"?'aria-pressed="true"':"")}</div>`;
  return switcher+(state.graphMode==="sources"||!W.case_map?sourceGraphView():caseMapView());
}

function mapNodeType(kind) {
  return {correspondent:"Email address", communication:"Email", financial_record:"Financial record",
    transaction:"Transaction reference", finding:"Draft finding", document:"Document", issue:"Counsel question", element:"Proof element", fact:"Cited fact", person:"Reviewed person", alias:"Reviewed alias"}[kind] || "Case object";
}

function caseGraphScope(preview) {
  const sources = new Set(visibleSources().map(s => s.source_id));
  const map = W.casework ? cwReviewGraph(W.case_map) : W.case_map;
  const scoped = state.sourceIds || state.query || state.address || state.from || state.to;
  const byId = new Map(map.nodes.filter(n => n.source_ids.some(id => sources.has(id)) ||
    (n.kind === "element" && !n.source_ids.length && !scoped)).map(n => [n.id, n]));
  const focus = preview ? null : byId.get(state.mapFocus);
  const search = preview ? "" : String(state.mapQuery ?? "").trim().toLocaleLowerCase();
  const seeds = focus ? new Set([focus.id]) : search ? new Set([...byId.values()].filter(n =>
    [n.label, n.detail, mapNodeType(n.kind)].some(value => value?.toLocaleLowerCase().includes(search))).map(n => n.id)) : null;
  const links = map.edges.map((link, index) => ({...link, id: String(index)})).filter(link =>
    byId.has(link.source) && byId.has(link.target) && link.evidence_ids.length &&
    link.evidence_ids.every(id => sources.has(evidenceById.get(id)?.source_id)) &&
    (!state.supportingOnly || link.kind !== "contrary") &&
    (!seeds || seeds.has(link.source) || seeds.has(link.target)));
  const linked = new Set(links.flatMap(link => [link.source, link.target]));
  const candidates = [...byId.values()].filter(n => linked.has(n.id) || (seeds ? seeds.has(n.id) : n.kind !== "finding" && n.kind !== "issue"));
  const nodeLimit = preview ? 12 : 32, edgeLimit = preview ? 13 : 49;
  const exemplars = ["support", "contrary", "Recorded reference", "From header", "To header", "Examined in draft"]
    .map(type => links.find(link => (link.kind || link.label) === type)).filter(Boolean);
  const displayed = new Set([...(seeds || [])].slice(0, nodeLimit)), edges = [];
  for (const link of new Set([...exemplars, ...links])) {
    const needed = new Set([link.source, link.target].filter(id => !displayed.has(id)));
    if (displayed.size + needed.size > nodeLimit) continue;
    edges.push(link);
    for (const id of needed) displayed.add(id);
    if (edges.length === edgeLimit) break;
  }
  for (const n of candidates) {
    if (displayed.size >= nodeLimit) break;
    if (!linked.has(n.id)) displayed.add(n.id);
  }
  return {sources, byId, focus, links, edges, nodes: candidates.filter(n => displayed.has(n.id)), count: candidates.length};
}

function layoutCaseGraph(nodes, edges) {
  // A fixed starting spiral and a bounded relaxation keep the layout stable on selection.
  const points = nodes.map((n, i) => ({id:n.id, x:Math.sqrt(i) * Math.cos(i * 2.4), y:Math.sqrt(i) * Math.sin(i * 2.4)}));
  const positions = new Map(points.map(p => [p.id, p]));
  for (let step = 0; step < 88; step++) {
    for (const p of points) { p.dx = -.16 * p.x; p.dy = -.16 * p.y; }
    for (let i = 0; i < points.length; i++) {
      const a = points[i];
      for (let j = i + 1; j < points.length; j++) {
        const b = points[j];
        const x = a.x - b.x, y = a.y - b.y, distance = Math.max(.04, Math.hypot(x, y));
        const force = (Math.min(5, .6 / distance ** 2) + 9 * Math.max(0, 1.2 - distance)) / distance;
        a.dx += x * force; a.dy += y * force; b.dx -= x * force; b.dy -= y * force;
      }
    }
    for (const link of edges) {
      const a = positions.get(link.source), b = positions.get(link.target);
      const x = a.x - b.x, y = a.y - b.y, distance = Math.max(.04, Math.hypot(x, y));
      const force = .38 * (distance - 1.4) / distance;
      a.dx -= x * force; a.dy -= y * force; b.dx += x * force; b.dy += y * force;
    }
    const speed = .07 * (1 - step / 88) + .018;
    for (const p of points) { p.x += p.dx * speed; p.y += p.dy * speed; }
  }
  for (const p of points) { p.x = Math.round(p.x * 194); p.y = Math.round(p.y * 76); }
  return positions;
}

function caseGraphCanvas(graph, preview, node, relationship) {
  const {nodes, edges, byId} = graph;
  const positions = layoutCaseGraph(nodes, edges), points = [...positions.values()];
  const left = Math.min(...points.map(p => p.x)), right = Math.max(...points.map(p => p.x));
  const top = Math.min(...points.map(p => p.y)), bottom = Math.max(...points.map(p => p.y));
  const width = Math.max(600, right - left + 190), height = Math.max(285, bottom - top + 72);
  const fit = [(left + right - width) / 2, (top + bottom - height) / 2, width, height].join(" ");
  const activeLinks = new Set(edges.filter(link => relationship ? relationship.id === link.id :
    node && (link.source === node.id || link.target === node.id)));
  const activeNodes = new Set([node?.id, ...[...activeLinks].flatMap(link => [link.source, link.target])]);
  const pairLinks = new Map();
  for (const link of edges) {
    const pair = JSON.stringify([link.source, link.target].sort());
    if (!pairLinks.has(pair)) pairLinks.set(pair, []);
    pairLinks.get(pair).push(link);
  }
  function renderLink(link, bend) {
    const a = positions.get(link.source), b = positions.get(link.target);
    const dx = b.x - a.x, dy = b.y - a.y, distance = Math.max(1, Math.hypot(dx, dy));
    const control = {x:(a.x+b.x)/2 - dy * bend / distance, y:(a.y+b.y)/2 + dx * bend / distance};
    function boundary(p) {
      const x = control.x - p.x, y = control.y - p.y;
      const scale = Math.min(77 / Math.max(.01, Math.abs(x)), 23 / Math.max(.01, Math.abs(y)));
      return `${p.x + x * scale} ${p.y + y * scale}`;
    }
    const path = `M${boundary(a)} Q${control.x} ${control.y} ${boundary(b)}`;
    const label = `${link.label}: ${byId.get(link.source).label} → ${byId.get(link.target).label}`;
    const tone = link.kind === "contrary" ? "contrary" : link.kind === "support" ? "support" : "recorded";
    const emphasis = activeLinks.has(link) ? "highlighted" : node || relationship ? "muted-edge" : "";
    return `<g class="map-link ${tone} ${emphasis}" data-action="map-link" data-id="${link.id}" role="button" aria-label="${e(label)}"><title>${e(label)}</title><path class="map-edge" d="${path}" marker-end="url(#case-arrow)"/><path class="map-hit" d="${path}"/></g>`;
  }
  const links = [...pairLinks.values()].flatMap(group => group.map((link, i) => {
    const direction = link.source < link.target ? 1 : -1;
    return renderLink(link, direction * (i - (group.length - 1) / 2) * 38);
  })).join("");
  const objects = nodes.map(n => {
    const p = positions.get(n.id), title = Array.from(n.label);
    const label = title.length > 20 ? title.slice(0,19).join("") + "…" : n.label;
    const active = node?.id === n.id || relationship?.source === n.id || relationship?.target === n.id;
    return `<g class="map-node ${e(n.kind)} ${active ? "active" : ""} ${(node || relationship) && !activeNodes.has(n.id) ? "muted-node" : ""}" data-action="map-node" data-id="${e(n.id)}" transform="translate(${p.x},${p.y})" tabindex="0" role="button" aria-pressed="${active}" aria-label="Inspect ${e(n.label)}"><title>${e(n.label)}${n.detail ? ` · ${e(n.detail)}` : ""}</title><rect x="-77" y="-23" width="154" height="46" rx="7"/><circle class="node-marker" cx="-64" cy="-10" r="3"/><text class="node-detail" x="-56" y="-7">${mapNodeType(n.kind)}</text><text class="node-title" x="-66" y="12" clip-path="url(#case-node-label)">${e(label)}</text></g>`;
  }).join("");
  return `<svg class="case-map" data-fit="${fit}" data-map-view="${preview ? "preview" : "full"}" viewBox="${fit}" ${preview ? "" : 'tabindex="0"'} aria-label="Case graph with selectable nodes and connections" role="group"><defs><marker id="case-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0 L7 3.5 L0 7 Z" fill="context-stroke"/></marker><clipPath id="case-node-label"><rect x="-66" y="-1" width="136" height="17"/></clipPath></defs>${links}${objects}</svg>`;
}

function caseGraphInspector(graph, node, relationship) {
  if (relationship) {
    const from = graph.byId.get(relationship.source), to = graph.byId.get(relationship.target);
    return `<h3>${e(relationship.label)}</h3><div class="actions">${btn(from.label,"map-node",from.id,`aria-label="Inspect ${e(from.label)}"`)}<span aria-hidden="true">→</span>${btn(to.label,"map-node",to.id,`aria-label="Inspect ${e(to.label)}"`)}</div><p>${e(relationship.qualification)}</p><h4>Source passages</h4><div class="actions">${evidenceButtons(relationship.evidence_ids)}</div><p>${btn("Clear selection","map-clear")}</p>`;
  }
  if (!node) return '<h3>Inspect the graph</h3><p>Select a node or connection to see its source passages.</p>';
  const links = graph.links.filter(link => link.source === node.id || link.target === node.id);
  const evidence = node.kind === "finding" || node.kind === "issue" ? links.flatMap(link => link.evidence_ids) : node.evidence_ids;
  const citations = [...new Set(evidence.filter(id => graph.sources.has(evidenceById.get(id)?.source_id)))];
  const read = node.kind === "finding" ? btn("View finding","finding",node.id) : node.kind === "document" ? btn("View document","source",node.source_ids[0]) : "";
  return `<span class="eyebrow">${mapNodeType(node.kind)}</span><h3>${e(node.label)}</h3>${node.detail ? `<p>${e(node.detail)}</p>` : ""}${node.date || node.date_label ? `<p>${e(node.date?.slice(0,10))} <small>${e(node.date_label)}</small></p>` : ""}<p>${e(node.qualification)}</p>
    <div class="actions">${read}${links.length && node.id !== graph.focus?.id ? btn("Focus on connections","map-focus",node.id) : ""}${btn("Clear selection","map-clear")}</div>
    ${citations.length ? `<h4>Source passages</h4>${evidenceButtons(citations.slice(0,8))}${citations.length>8 ? `<p>${citations.length-8} more passages on individual connections.</p>` : ""}` : ""}
    ${links.length ? `<h4>Connections (${links.length})</h4><ul class="map-connections">${links.slice(0,12).map(link => {
      const other = graph.byId.get(link.source === node.id ? link.target : link.source);
      return `<li>${btn(`${link.label} · ${other.label}`,"map-link",link.id)}</li>`;
    }).join("")}</ul>${links.length>12 ? '<p>Use search or the connections table to narrow the view.</p>' : ""}` : ""}`;
}

function caseMapView(preview=false) {
  const graph = caseGraphScope(preview), {nodes, edges, links, count, focus, byId} = graph;
  const node = preview ? null : byId.get(state.mapSelection);
  const relationship = preview ? null : links.find(link => link.id === state.mapEdge);
  const counts = `${nodes.length}${nodes.length < count ? ` of ${count}` : ""} nodes · ${edges.length}${edges.length < links.length ? ` of ${links.length}` : ""} connections`;
  const legend = [["support", "Supporting citation"], ["contrary", "Contrary citation"]]
    .filter(([kind]) => edges.some(link => link.kind === kind))
    .map(([kind,label]) => `<span class="map-key ${kind}">${label}</span>`).join("");
  const canvas = nodes.length ? `<div class="map-canvas"><div class="map-tools"><span>${counts}</span>${preview ? "" : `<div class="actions">${btn("−","map-zoom","out",'aria-label="Zoom out"')}${btn("+","map-zoom","in",'aria-label="Zoom in"')}${btn("Fit","map-zoom","fit",'aria-label="Fit case graph"')}</div>`}</div>${caseGraphCanvas(graph,preview,node,relationship)}${legend ? `<div class="map-legend" aria-label="Connection styles">${legend}</div>` : ""}</div>` : empty("No graph objects match this view.");
  if (preview) return `<section class="card case-graph-preview" aria-labelledby="case-graph-heading"><div class="section-title"><h3 id="case-graph-heading">Case graph</h3>${W.casework?btn("Ask the case graph","view","Case questions"):""}${btn("Explore graph","open-map")}</div>${canvas}</section>`;
  const map = W.case_map;
  return `<div class="page-intro"><div><h2 id="case-graph-heading" tabindex="-1">Case graph</h2><p>${e(map.definition)}</p></div></div>
    ${W.casework?routeTabs([["Case graph","People & relationships"],["Ask the graph","Case questions"],["Witness preparation","Witness preparation"],["Identities","Identity review"]]):""}
    ${W.casework&&cwReturnScope?btn("Back to question","cw-back-to-question"):""}
    <form id="case-graph-search" class="map-search" role="search"><label>Find graph objects<input id="case-graph-query" maxlength="200" type="search" value="${e(state.mapQuery)}" placeholder="Name, document or reference"></label><button type="submit">Search graph</button>${state.mapQuery ? btn("Clear search","map-search-clear") : ""}</form>
    ${focus ? `<div class="map-focus"><strong>Connections to ${e(focus.label)}</strong>${btn("Leave focus","map-focus","")}</div>` : ""}
    <div class="graph-workspace">${canvas}<aside class="card node-inspector" aria-label="Selected graph item" aria-live="polite">${caseGraphInspector(graph,node,relationship)}</aside></div>
    <details><summary>Graph coverage</summary><p>${counts} in this view. The graph groups verified locations and draft citations. ${map.omitted_communications || 0} communications, ${map.omitted_header_addresses || 0} header addresses, ${map.omitted_financial_records || 0} financial records and ${map.omitted_documents || 0} unlinked documents exceed the projection limits.</p></details>
    ${edges.length ? `<details><summary>Inspect connections as a table</summary>${table(["From","Connection","To","Evidence"],edges.map(link=>[e(byId.get(link.source).label),btn(link.label,"map-link",link.id),e(byId.get(link.target).label),evidenceButtons(link.evidence_ids)]))}</details>` : ""}`;
}
function readingChronology() {
  const sources=new Set(visibleSources().map(s=>s.source_id));
  const events=W.case_map.nodes.filter(n=>["communication","financial_record"].includes(n.kind)&&n.source_ids.some(id=>sources.has(id))).filter(n=>{const day=n.date?.slice(0,10);return (!state.from&&!state.to)||day&&(!state.from||day>=state.from)&&(!state.to||day<=state.to);}).sort((a,b)=>(a.date||"9999").localeCompare(b.date||"9999"));
  return `<div class="page-intro"><div><h2>Timeline</h2><p>Email dates and counsel-labelled financial events. Undated records stay unresolved; financial dates retain their annotation basis.</p></div>${btn("Open event graph","open-map")}</div><div class="timeline reading-timeline">${events.map(n=>`<article><span class="eyebrow">${e(n.date?.slice(0,10)||"Date unresolved")} · ${n.kind==="communication"?"Communication":"Financial record"}</span><h3>${e(n.label)}</h3><small>${e(n.date_label)}</small><p>${e(n.qualification)}</p>${evidenceButtons(n.evidence_ids)}</article>`).join("")||empty("No event records match this scope.")}</div><details><summary>Inspect transaction arithmetic</summary>${transactionReview()}</details>`;
}
document.addEventListener("click",event=>{
  const button=event.target.closest("[data-action]");if(!button)return;
  const {action,id}=button.dataset;
  if(action==="coverage") {
    const ids=coverageSources(id);
    if(ids)goto({view:"Evidence Explorer",sourceIds:ids,query:"",address:"",from:"",to:"",source:null});
  }
  else if(action==="select-report")goto({reportId:id});
  else if(action==="download-report"){const report=W.reading_reports?.find(r=>r.id===id);if(report)download(report.filename,report.markdown,"text/markdown");}
  else if(action==="report-heading"){const heading=document.getElementById(`report-heading-${id}`);heading?.scrollIntoView({block:"start",behavior:"smooth"});}
  else if(action==="graph-mode")goto({graphMode:id,graphPaths:false});
  else if(action==="open-map"||action==="map-node"||action==="map-link"){
    const enter = state.view === "Overview" || action === "open-map";
    goto({view:"People & relationships", graphMode:"case",
      mapSelection:action==="map-node" && (enter || state.mapSelection!==id) ? id : "",
      mapEdge:action==="map-link" && (enter || state.mapEdge!==id) ? id : "",
      ...(enter ? {mapQuery:"",mapFocus:""} : {})});
  }
  else if(action==="map-clear")goto({mapSelection:"",mapEdge:""});
  else if(action==="map-focus")goto({mapFocus:id,mapEdge:""});
  else if(action==="map-search-clear")goto({mapQuery:"",mapSelection:"",mapEdge:"",mapFocus:""});
  else if(action==="map-zoom")zoomCaseGraph(document.querySelector('.case-map'),id);
  else if(action==="reading-task"){
    const task=W.reading_tasks.find(t=>t.id===id);if(!task)return;
    const content=`${pills(task.status)}<p><strong>Record:</strong> ${e(task.record)}</p><p><strong>Decision it informs:</strong> ${e(task.purpose)}</p><p><strong>Closure test:</strong> ${e(task.closure)}</p><p>Owner: ${e(task.owner)}</p><p class="muted">${e(task.origin)}</p><div class="actions">${evidenceButtons(task.evidence_ids)}</div>`;
    reportUI.openInspector(task.title,content,button);
  }
});

document.addEventListener("submit", event => {
  if (event.target.id !== "case-graph-search") return;
  event.preventDefault();
  goto({mapQuery:document.getElementById("case-graph-query").value,mapFocus:"",mapSelection:"",mapEdge:""});
});

function zoomCaseGraph(svg, action) {
  if (!svg) return;
  if (action === "fit") {
    svg.setAttribute("viewBox",svg.dataset.fit);
    return;
  }
  const {x,y,width,height} = svg.viewBox.baseVal;
  const fittedWidth = Number(svg.dataset.fit.split(" ")[2]);
  const target = Math.max(.24 * fittedWidth, Math.min(1.25 * fittedWidth, width * (action === "in" ? .8 : 1.25)));
  const targetHeight = height * target / width;
  svg.setAttribute("viewBox",[x + (width - target)/2, y + (height - targetHeight)/2, target, targetHeight].join(" "));
}

document.addEventListener("keydown",event=>{
  if(["Enter"," "].includes(event.key)&&event.target.matches('.map-node')){event.preventDefault();event.target.dispatchEvent(new MouseEvent("click",{bubbles:true}));}
  if (!event.target.matches('.case-map[data-map-view="full"]')) return;
  const svg = event.target;
  if (["+","-","Home"].includes(event.key)) {
    event.preventDefault();
    zoomCaseGraph(svg,{"+":"in","-":"out",Home:"fit"}[event.key]);
  }
  const pan = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
  if (pan) {
    event.preventDefault();
    const {x,y,width,height} = svg.viewBox.baseVal;
    svg.setAttribute("viewBox",[x+pan[0]*width/10,y+pan[1]*height/10,width,height].join(" "));
  }
});

document.addEventListener("pointerdown", event => {
  const svg = event.target.closest('.case-map[data-map-view="full"]');
  if (!svg || event.button !== 0 || event.target.closest("[data-action]")) return;
  const scale = svg.getScreenCTM()?.a;
  if (!scale) return;
  const {x,y,width,height} = svg.viewBox.baseVal;
  function move(pointer) {
    svg.setAttribute("viewBox",[x-(pointer.clientX-event.clientX)/scale,
      y-(pointer.clientY-event.clientY)/scale,width,height].join(" "));
  }
  svg.setPointerCapture(event.pointerId);
  svg.classList.add("panning");
  svg.addEventListener("pointermove", move);
  svg.addEventListener("lostpointercapture", () => {
    svg.removeEventListener("pointermove", move);
    svg.classList.remove("panning");
  }, {once:true});
});
