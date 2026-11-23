/* Build the review diagram from the same authorized questions and passages as the brief.
   Planning links describe the investigation. Only record-backed links carry citations. */
function buildCaseGraph() {
  const nodes = new Map(), edges = new Map(), recordBySource = new Map();
  const sources = new Map(visibleSources().map(source => [source.source_id, source]));
  const filtered = !!(state.sourceIds || state.query || state.address || state.from || state.to);
  const goal = "case:goal";
  function node(id, kind, type, label, detail = "", action = null) {
    if (!nodes.has(id)) nodes.set(id, {id, kind, type, label, detail, action, citations:new Set()});
    return nodes.get(id);
  }
  function link(from, to, label, role, citations = [], detail = "") {
    const id = JSON.stringify([from, to, label]);
    if (!edges.has(id)) edges.set(id, {id, source:from, target:to, label, role, detail, citations:new Set()});
    const edge = edges.get(id);
    for (const passage of citations) edge.citations.add(passage);
    return edge;
  }
  function available(id) {
    return sources.has(evidenceById.get(id)?.source_id);
  }
  function inScope(ids) {
    return ids.length ? ids.every(available) : !filtered;
  }
  function record(sourceId) {
    const source = sources.get(sourceId);
    // Identical derivatives appear once in the diagram. Each collected copy and its
    // own passage IDs stay available for inspection and attribution.
    const identity = source.content_sha256 ? [source.media_type, source.content_sha256] : [sourceId];
    const item = node("record:" + JSON.stringify(identity), "evidence", documentType(source), documentTitle(source),
      source.relative_path, ["source", sourceId]);
    if (!item.sourceIds) item.sourceIds = new Set();
    item.sourceIds.add(sourceId);
    recordBySource.set(sourceId, item);
    return item;
  }
  function cite(item, ids, label, role) {
    for (const id of ids) {
      if (!available(id)) continue;
      const document = record(evidenceById.get(id).source_id);
      document.citations.add(id);
      item.citations.add(id);
      link(item.id, document.id, label, role, [id]);
    }
  }
  function citations(item, support, contrary) {
    const disputed = new Set(contrary);
    cite(item, support.filter(id => !disputed.has(id)), "Supporting passage", "support");
    if (!state.supportingOnly) cite(item, contrary, "Contrary passage", "contrary");
  }
  node(goal, "goal", "Case goal", W.goal || W.title, W.matter_scope?.intended_decision || "");
  for (const q of W.counsel_issues || []) {
    const support = q.supporting_evidence || [], contrary = q.counter_evidence || [];
    if (!inScope([...support, ...contrary])) continue;
    const item = node("counsel:" + q.id, "question", "Counsel question", q.question, q.framework_basis);
    item.status = q.status;
    link(goal, item.id, "Question from counsel", "plan");
    citations(item, support, contrary);
  }
  for (const q of W.issues) {
    const support = q.supporting_evidence || [], contrary = q.contradictory_evidence || [];
    if (!inScope([...support, ...contrary])) continue;
    const item = node("question:" + q.id, "question", q.parent_id ? "Follow-up question" : "Investigation question",
      reviewLabel(q.question), q.assessment || "", ["issue", q.id]);
    item.status = [q.origin, q.status].filter(Boolean).join(" · ");
    citations(item, support, contrary);
    item.hypotheses = [...new Set(q.alternatives || [])].filter(text => typeof text === "string" && text.trim());
    for (const [index, wording] of item.hypotheses.entries()) {
      const hypothesis = node("hypothesis:" + q.id + ":" + index, "hypothesis", "Working hypothesis", wording,
        "An alternative explanation recorded for this question.", ["issue", q.id]);
      link(item.id, hypothesis.id, "Considers explanation", "plan");
    }
  }
  for (const q of W.issues) {
    const id = "question:" + q.id;
    if (!nodes.has(id)) continue;
    const parent = "question:" + q.parent_id;
    if (q.parent_id && nodes.has(parent)) link(parent, id, "Follow-up question", "plan");
    else link(goal, id, "Investigation question", "plan");
    for (const counsel of q.counsel_issue_ids || []) {
      if (nodes.has("counsel:" + counsel)) link("counsel:" + counsel, id, "Examines question", "plan");
    }
  }
  for (const finding of W.findings) {
    const f = currentReview(finding);
    if (["Needs correction", "Dismissed"].includes(f.review_state) ||
        !inScope([...f.supporting_evidence, ...f.counter_evidence])) continue;
    const reviewed = ["Reviewed with qualification", "Revised"].includes(f.review_state);
    const item = node("finding:" + f.id, "finding", reviewed ? "Reviewed finding" : "Draft finding", f.title,
      reviewed && f.reviewed_text ? f.reviewed_text : f.assessment, ["finding", f.id]);
    item.status = f.review_state;
    const parents = [...(f.issue_ids || []).map(id => "question:" + id),
      ...(f.counsel_issue_ids || []).map(id => "counsel:" + id)].filter(id => nodes.has(id));
    for (const parent of parents.length ? parents : [goal]) link(parent, item.id, "Addresses", "plan");
    citations(item, f.supporting_evidence, f.counter_evidence);
  }

  const book = W.casework;
  if (book) {
    const elements = new Map(book.elements.map(el => [el.id, el]));
    function proofElement(el) {
      const item = node("element:" + el.id, "question", "Proof element", el.title, el.group, ["view", "Proof chart"]);
      const owners = (W.counsel_issues || []).filter(q => nodes.has("counsel:" + q.id) &&
        q.question === el.group && q.kind === el.kind && q.elements?.includes(el.title));
      link(owners.length === 1 ? "counsel:" + owners[0].id : goal, item.id, "Proof to establish", "plan");
      return item;
    }
    if (!filtered) for (const el of book.elements) proofElement(el);
    for (const fact of book.facts) {
      const passage = "work-" + fact.id;
      if (!sources.has(fact.anchor.source) || !cwRegister(passage, fact.anchor) ||
          (state.supportingOnly && fact.role === "Contrary")) continue;
      const item = node("fact:" + fact.id, "finding", "Counsel statement", fact.wording, fact.actor);
      item.status = fact.approved ? "Wording reviewed by counsel" : "Wording awaiting review";
      const el = elements.get(fact.element);
      const role = fact.role === "Contrary" ? "contrary" : fact.role === "Support" ? "support" : "context";
      link(el ? proofElement(el).id : goal, item.id, fact.role + " · counsel annotation", role, [passage]);
      cite(item, [passage], "Quoted passage", "context");
      if (fact.witness) {
        const person = node("witness:" + fact.witness, "person", "Attributed witness", fact.witness);
        link(item.id, person.id, "Statement attributed to", "person", [passage], "Attribution recorded by counsel.");
        person.citations.add(passage);
      }
    }
    for (const alias of cwAliases()) {
      const fact = nodes.get("fact:" + alias.fact);
      if (!fact) continue;
      const person = node("witness:" + alias.person, "person", "Reviewed person", alias.person);
      const name = node("alias:" + alias.id, "person", "Confirmed alias", alias.alias);
      link(fact.id, person.id, "Identity record", "person", fact.citations);
      link(person.id, name.id, "Confirmed identity", "person", fact.citations, "Identity link confirmed by counsel.");
      for (const id of fact.citations) { person.citations.add(id); name.citations.add(id); }
    }
  }
  for (const event of W.financial_review?.events || []) {
    if (!event.evidence_ids?.length || !event.evidence_ids.every(available) || !sources.has(event.source_id)) continue;
    const isNew = !recordBySource.has(event.source_id);
    const doc = record(event.source_id);
    if (isNew) link(goal, doc.id, "Financial exhibit", "context", event.evidence_ids, event.classification_basis);
    const ref = node("transaction:" + event.transaction_ref, "reference", "Transaction reference", event.transaction_ref);
    link(doc.id, ref.id, event.event_type.replace(/_/g, " ") + " · " + event.currency + " " + event.amount,
      "context", event.evidence_ids, event.classification_basis);
    for (const id of event.evidence_ids) { doc.citations.add(id); ref.citations.add(id); }
  }
  // Headers are read from cited source versions, including messages beyond the timeline preview.
  // A mailbox and a counsel-identified person retain separate identities.
  for (const event of W.temporal.events) {
    for (const sid of event.source_ids) {
      const doc = recordBySource.get(sid);
      if (!doc) continue;
      const refs = event.evidence_refs.map(ref => ref.evidence_id).filter(id => evidenceById.get(id)?.source_id === sid);
      if (!refs.length) continue;
      for (const [field, addresses] of Object.entries(event.fields.headers)) {
        for (const address of addresses) {
          const person = node("mailbox:" + address, "person", "Email address", address);
          for (const id of refs) person.citations.add(id);
          link(doc.id, person.id, field + " header", "person", refs, event.qualification);
        }
      }
    }
  }
  const connections = new Map([...nodes.keys()].map(id => [id, []]));
  for (const edge of edges.values()) {
    connections.get(edge.source).push(edge);
    connections.get(edge.target).push(edge);
  }
  return {nodes, edges, connections, goal};
}

function caseGraphWindow(model, branch, query, limit, showHypotheses = false) {
  const {nodes, connections, goal} = model;
  function walk(seeds, downstream) {
    const seen = new Set(seeds);
    for (const id of seen) for (const edge of connections.get(id)) {
      if (downstream && edge.source === id) seen.add(edge.target);
      if (!downstream && edge.target === id) seen.add(edge.source);
    }
    return seen;
  }
  let eligible = nodes.has(branch)
    ? new Set([...walk([branch], true), ...walk([branch], false)]) : new Set(nodes.keys());
  const term = String(query || "").trim().toLowerCase();
  let matches = [];
  if (term) {
    matches = [...eligible].filter(id => {
      const item = nodes.get(id);
      return [item.label, item.type, item.status, item.detail].some(value => value?.toLowerCase().includes(term));
    });
    const context = walk(matches, false);
    for (const id of matches) for (const edge of connections.get(id)) context.add(edge.target);
    eligible = new Set([...eligible].filter(id => context.has(id)));
  } else if (!showHypotheses) {
    for (const id of eligible) if (nodes.get(id).kind === "hypothesis") eligible.delete(id);
  }
  // Remember the shortest path to each item. Reserve that path for a match
  // before filling the remaining space, so a bounded view has no orphan nodes.
  const parents = new Map();
  if (eligible.has(goal)) parents.set(goal, null);
  for (const id of parents.keys()) for (const edge of connections.get(id)) {
    if (edge.source === id && eligible.has(edge.target) && !parents.has(edge.target)) parents.set(edge.target, id);
  }
  const pins = [branch, ...matches];
  // In a large matter, show a few complete evidence trails before filling the
  // overview with more questions. Give contrary passages a place alongside support.
  if (!term && parents.size > limit) {
    const roots = branch ? [branch] : connections.get(goal).map(edge => edge.target);
    for (const root of roots.slice(0, Math.max(1, Math.floor(limit/6)))) {
      pins.push(root);
      const roles = new Set();
      for (const id of walk([root], true)) {
        for (const link of connections.get(id)) {
          if (link.source !== id || !parents.has(link.target) || roles.has(link.role)) continue;
          if (nodes.get(link.target).kind === "evidence" || link.role === "person") {
            pins.push(id, link.target);
            roles.add(link.role);
          }
        }
        if (roles.size >= 4) break;
      }
    }
  }
  const ids = new Set();
  for (const pin of pins) {
    if (!parents.has(pin)) continue;
    const path = [];
    for (let id = pin; id && !ids.has(id); id = parents.get(id)) path.push(id);
    if (ids.size + path.length <= limit) for (const id of path.reverse()) ids.add(id);
    if (ids.size === limit) break;
  }
  for (const id of parents.keys()) {
    if (ids.size === limit) break;
    ids.add(id);
  }
  return {nodes:[...ids].map(id => nodes.get(id)),
    edges:[...model.edges.values()].filter(edge => ids.has(edge.source) && ids.has(edge.target)),
    total:eligible.size, matches};
}
