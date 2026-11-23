/* The graph is mounted only for its report page. Selection leaves the canvas and camera in place. */
let caseGraphPage = null;

function caseGraphView() {
  if (W.package_mode === "approved_excerpt_briefing") return "";
  const model = buildCaseGraph();
  const branch = model.nodes.has(state.mapFocus) ? state.mapFocus : "";
  const limit = Math.max(32, Math.min(160, Number(state.mapLimit) || 32));
  const slice = caseGraphWindow(model, branch, state.mapQuery, limit, state.mapHypotheses);
  caseGraphPage = {model, slice, cards:new Map(), selected:null};
  const all = [...model.nodes.values()];
  const branches = all.filter(n => n.kind === "question");
  const questions = branches.filter(n => n.type !== "Proof element");
  const elements = branches.filter(n => n.type === "Proof element");
  const hypotheses = all.filter(n => n.kind === "hypothesis");
  const people = all.filter(n => n.kind === "person");
  const addresses = people.filter(n => n.type === "Email address");
  const aliases = people.filter(n => n.type === "Confirmed alias");
  const counts = [[questions.length, "question", "questions"],
    [elements.length, "proof element", "proof elements"], [hypotheses.length, "working hypothesis", "working hypotheses"],
    [all.filter(n => n.kind === "evidence").length, "distinct cited document", "distinct cited documents"],
    [people.length - addresses.length - aliases.length, "named person", "named people"],
    [addresses.length, "email address", "email addresses"], [aliases.length, "confirmed alias", "confirmed aliases"]]
    .filter(([n]) => n > 0)
    .map(([n, one, many]) => n + " " + (n === 1 ? one : many)).join(" · ");
  const branchOptions = group => group.map(n => `<option value="${e(n.id)}" ${branch === n.id ? "selected" : ""}>${e(n.label)}</option>`).join("");
  const rows = slice.nodes.map(n => `<li>${btn(n.label, "map-node", n.id)}<small>${e(n.type)}</small></li>`).join("");
  const hasMore = slice.nodes.length < slice.total;
  return `<section class="case-graph-page" aria-labelledby="case-graph-heading">
    <div class="page-intro"><div><h2 id="case-graph-heading" tabindex="-1">Case graph</h2>${counts ? `<p>${e(counts)}</p>` : ""}</div></div>
    <div class="case-graph-shell"><div class="case-graph-tools">
      ${branches.length ? `<label>Question branch<select id="case-graph-branch"><option value="">All branches</option>${branchOptions(questions)}${elements.length ? `<optgroup label="Proof elements">${branchOptions(elements)}</optgroup>` : ""}</select></label>` : ""}
      <form id="case-graph-search" role="search"><label>Find in graph<input type="search" id="case-graph-query" maxlength="200" placeholder="Question, record or person" value="${e(state.mapQuery)}"></label><button id="case-graph-submit">Search graph</button>${state.mapQuery ? btn("Clear", "map-search-clear", "", 'id="case-graph-clear"') : ""}</form>
      ${hypotheses.length && !state.mapQuery ? btn(state.mapHypotheses ? "Hide hypotheses" : "Show hypotheses", "map-hypotheses", "", `id="case-graph-hypotheses" aria-pressed="${!!state.mapHypotheses}"`) : ""}
      ${slice.nodes.length ? `<div class="case-graph-camera" role="group" aria-label="Graph controls">
          ${btn("−","map-zoom","out",'aria-label="Zoom out" title="Zoom out"')}
          <output id="case-graph-scale" aria-label="Zoom level"></output>
          ${btn("+","map-zoom","in",'aria-label="Zoom in" title="Zoom in"')}
          ${btn("Fit","map-zoom","fit",'aria-label="Fit case graph" title="Fit the whole graph"')}
        </div>` : ""}</div>${slice.nodes.length ? `<div class="case-graph-stage" role="region" aria-label="Interactive case graph" aria-description="Drag or use the arrow keys to pan. Use plus and minus to zoom, or Home to fit the graph." tabindex="0">
        <div id="case-graph-canvas"></div><canvas id="case-graph-minimap" width="232" height="128" aria-hidden="true" title="Click to center the graph"></canvas>
      </div>` : empty("No graph items match this search. Clear the search or choose another question.")}
      <div class="case-graph-caption"><span>${hasMore ? slice.nodes.length + " of " + slice.total : slice.nodes.length} ${slice.total === 1 ? "item" : "items"}${state.mapQuery ? ` · ${slice.matches.length} ${slice.matches.length === 1 ? "match" : "matches"}` : ""}</span>
        <div class="case-edge-legend">${[["plan","Case structure"],["support","Supporting"],["contrary","Contrary"],["context","Context"],["person","Attribution"]].filter(([role]) => slice.edges.some(edge => edge.role === role)).map(([role,label]) => `<span class="edge-key ${role}">${label}</span>`).join("")}</div>
        ${hasMore && limit < 160 ? btn("Show more items","map-more") : hasMore ? "<small>Search or choose a branch to see more.</small>" : ""}</div></div>
    ${slice.nodes.length ? '<section id="case-graph-detail" aria-label="Selected graph item" aria-live="polite"></section>' : ""}
    ${model.nodes.size === 1 && !branch && !state.mapQuery ? '<p class="muted">No questions or evidence links are recorded in this scope.</p>' : ""}
    ${rows ? `<details class="case-graph-index"><summary>Browse graph as a list</summary><ul>${rows}</ul></details>` : ""}
  </section>`;
}

function caseGraphSelection() {
  const page = caseGraphPage;
  if (!page?.slice.nodes.length) return;
  const {model, slice, cy, cards} = page;
  const edge = slice.edges.find(link => link.id === state.mapEdge);
  const node = !edge && (slice.nodes.find(item => item.id === state.mapSelection) || slice.nodes[0]);
  const trace = !!(state.mapTrace && node && node.id !== model.goal);
  const key = JSON.stringify([edge?.id || node.id, trace]);
  if (page.selected === key) return;
  page.selected = key;
  const explicit = !!(edge || state.mapSelection === node?.id);
  const links = edge ? [edge] : slice.edges.filter(link => link.source === node.id || link.target === node.id);
  const highlighted = new Set(trace ? [] : links);
  if (trace) {
    const path = new Set([node.id]);
    for (const id of path) for (const incoming of slice.edges) {
      if (incoming.target === id) { highlighted.add(incoming); path.add(incoming.source); }
    }
  }
  const neighbors = new Set([...highlighted].flatMap(x => [x.source, x.target]));
  for (const [id, card] of cards) {
    card.classList.toggle("is-selected", explicit && node?.id === id);
    card.classList.toggle("is-dim", explicit && id !== node?.id && !neighbors.has(id));
    card.setAttribute("aria-pressed", String(explicit && node?.id === id));
  }
  if (cy && explicit && node) {
    const item = cy.getElementById(node.id), box = item.renderedBoundingBox();
    if (box.x2 < 0 || box.x1 > cy.width() || box.y2 < 0 || box.y1 > cy.height()) cy.center(item);
  }
  if (cy) cy.batch(() => {
    cy.edges().removeClass("is-dim is-active is-inspected");
    if (!explicit) return;
    cy.edges().addClass("is-dim");
    for (const link of highlighted) cy.getElementById(link.id).removeClass("is-dim").addClass("is-active");
    if (edge) cy.getElementById(edge.id).addClass("is-inspected");
  });
  const inspector = document.getElementById("case-graph-detail");
  if (!inspector) return;
  const previousControl = document.activeElement?.closest('#case-graph-detail [data-action]')?.dataset.action;
  const refs = [...(edge || node).citations];
  const passageRows = refs.map(ref => {
    const passage = evidenceById.get(ref), source = sourceById.get(passage.source_id);
    const quote = W.case_brief?.highlights?.find(h => h.evidence_id === ref)?.excerpt ||
      (passage.text.length > 200 ? passage.text.slice(0, 200) + "…" : passage.text);
    return `<div class="case-passage">${btn(documentTitle(source), "evidence", ref, `title="${e(source.relative_path)}"`)}
      <small>Characters ${e(passage.start_offset)}–${e(passage.end_offset)}</small>${quote ? `<blockquote>${e(quote)}</blockquote>` : ""}</div>`;
  });
  const passages = refs.length ? `<div class="case-graph-passages"><h4>Source passages</h4>${passageRows.slice(0, 3).join("")}
    ${refs.length > 3 ? `<details><summary>${refs.length - 3} more passages</summary>${passageRows.slice(3).join("")}</details>` : ""}</div>` : "";
  if (edge) {
    const from = model.nodes.get(edge.source), to = model.nodes.get(edge.target);
    inspector.innerHTML = `<h3>${e(edge.label)}</h3><div class="case-inspect-path">${btn(from.label, "map-node", from.id)}<span aria-hidden="true">→</span>${btn(to.label, "map-node", to.id)}</div>
      ${edge.detail ? `<p>${e(edge.detail)}</p>` : ""}${passages}`;
  } else {
    const copies = node.sourceIds?.size > 1 ? [...node.sourceIds] : [];
    const [action, id] = copies.length ? [] : node.action || [];
    const actionLabel = {source:"Open source", issue:"Review question", finding:"View finding", view:"Open proof chart"}[action];
    const connections = links.map(link => {
      const other = model.nodes.get(link.source === node.id ? link.target : link.source);
      return `<li>${btn(link.label + " · " + other.label, "map-edge", link.id)}</li>`;
    }).join("");
    inspector.innerHTML = `<div class="case-detail-heading"><div><span class="case-detail-type" data-kind="${node.kind}">${e(node.type)}</span><h3>${e(node.label)}</h3></div>
      <div class="actions">${node.id !== model.goal ? btn("Trace to case goal","map-trace",node.id,`aria-pressed="${trace}"`) : ""}${action ? btn(actionLabel, action, id) : ""}</div></div>${node.status ? `<small>${e(node.status)}</small>` : ""}
      ${copies.length ? `<details><summary>Identical text in ${copies.length} collected copies</summary><ul class="case-detail-links">${copies.map(sid => `<li>${btn(sourceById.get(sid).relative_path, "source", sid)}</li>`).join("")}</ul></details>` :
        node.detail && node.detail !== node.label ? `<p>${e(node.detail)}</p>` : ""}${passages}
      ${node.hypotheses?.length ? `<details><summary>Working hypotheses (${node.hypotheses.length})</summary><ul>${node.hypotheses.map(h => `<li>${e(h)}</li>`).join("")}</ul></details>` : ""}
      ${connections ? `<details><summary>Connections (${links.length})</summary><ul class="case-detail-links">${connections}</ul></details>` : ""}`;
  }
  reportUI.enhance(inspector);
  if (previousControl === "map-trace") inspector.querySelector('[data-action="map-trace"]')?.focus({preventScroll:true});
  else if (previousControl === "map-edge" || previousControl === "map-node") {
    const heading = inspector.querySelector("h3");
    heading.tabIndex = -1;
    heading.focus({preventScroll:true});
  }
}

function caseGraphZoom(action) {
  const cy = caseGraphPage?.cy;
  if (!cy) return;
  if (action === "fit") cy.fit(cy.elements(), 28);
  else cy.zoom({level:cy.zoom() * (action === "in" ? 1.25 : .8), renderedPosition:{x:cy.width()/2, y:cy.height()/2}});
}

function routeCaseGraphEdges(cy, narrow) {
  const axis = narrow ? "x" : "y";
  const ports = new Map(cy.edges().map(edge => [edge.id(), {}]));
  for (const node of cy.nodes()) for (const side of ["source", "target"]) {
    const other = side === "source" ? "target" : "source";
    const ordered = node.connectedEdges().filter(edge => edge.data(side) === node.id())
      .sort((a,b) => a[other]().position(axis) - b[other]().position(axis) || a.id().localeCompare(b.id()));
    ordered.forEach((edge, i) => {
      const offset = ordered.length > 1 ? .5*i/(ordered.length-1)-.25 : 0;
      const end = side === "source" ? .5 : -.5;
      const [x,y] = narrow ? [offset,end] : [end,offset];
      const port = ports.get(edge.id());
      const center = node.position();
      port[side] = {x:center.x + x*node.data("width"), y:center.y + y*node.data("height")};
      edge.style(side + "-endpoint", 100*x + "% " + 100*y + "%");
      if (side === "source") port.turn = .35 + .3*(i+1)/(ordered.length+1);
    });
  }
  for (const edge of cy.edges()) {
    const {source, target, turn} = ports.get(edge.id());
    const route = edge.scratch();
    // Dagre routes long links around intervening ranks. Adjacent ranks use two
    // orthogonal bends between their assigned ports, including parallel citations.
    if (route.controlPointWeights?.length > 1) {
      edge.style({"curve-style":"round-segments", "segment-weights":route.controlPointWeights,
        "segment-distances":route.controlPointDistances});
      continue;
    }
    if (Math.abs(source[axis]-target[axis]) < 1) { edge.style("curve-style","straight"); continue; }
    const lane = narrow ? source.y + (target.y-source.y)*turn : source.x + (target.x-source.x)*turn;
    const bends = narrow ? [[source.x,lane],[target.x,lane]] : [[lane,source.y],[lane,target.y]];
    // Cytoscape expresses bend positions along and perpendicular to the line of centers.
    const start = edge.source().position(), finish = edge.target().position();
    const dx = finish.x-start.x, dy = finish.y-start.y, length = Math.hypot(dx,dy);
    const weights = bends.map(([x,y]) => ((x-start.x)*dx + (y-start.y)*dy)/(length*length));
    const distances = bends.map(([x,y]) => ((y-start.y)*dx - (x-start.x)*dy)/length);
    edge.style({"curve-style":"round-segments", "segment-weights":weights, "segment-distances":distances});
  }
}

function mountCaseGraph() {
  const page = caseGraphPage, host = document.querySelector("#case-graph-canvas");
  if (!host || !page) return;
  const {slice, cards} = page;
  // Supply Cytoscape's container positioning in the existing, CSP-hashed report stylesheet.
  document.head.querySelector("style").id = "__________cytoscape_stylesheet";
  const theme = window.matchMedia("(prefers-color-scheme: dark)");
  function palette() {
    return theme.matches ? {plan:"#a1a1aa", support:"#52ba98", contrary:"#fb929b", person:"#c6a075", context:"#89a6cd"}
      : {plan:"#96929f", support:"#37816a", contrary:"#c65260", person:"#a58867", context:"#6e839f"};
  }
  function styles() {
    const colors = palette();
    return [
      {selector:"node", style:{width:"data(width)", height:"data(height)", shape:"round-rectangle", "background-opacity":0}},
      {selector:"edge", style:{width:1.5, "curve-style":"straight", "segment-radii":7, "edge-distances":"node-position",
        "target-arrow-shape":"triangle", "arrow-scale":.75,
        "line-color":ele => colors[ele.data("role")], "target-arrow-color":ele => colors[ele.data("role")],
        "overlay-padding":8, "text-rotation":"none", "font-size":11}},
      {selector:'edge[role="contrary"]', style:{"line-style":"dashed", width:2}},
      {selector:"edge.is-dim", style:{opacity:.22}},
      {selector:"edge.is-active", style:{width:2.7}},
      {selector:"edge.is-inspected, edge.is-hovered", style:{label:"data(label)", color:theme.matches ? "#fafafa" : "#27272a",
        "text-background-color":theme.matches ? "#27272a" : "#ffffff", "text-background-opacity":1, "text-background-padding":3}}
    ];
  }
  const cy = page.cy = cytoscape({container:host, layout:{name:"preset"}, style:styles(),
    elements:[...slice.nodes.map(n => ({data:{id:n.id, width:216, height:60}})), ...slice.edges.map(edge => ({
      data:{id:edge.id, source:edge.source, target:edge.target, role:edge.role, label:edge.label}}))],
    minZoom:.08, maxZoom:2.4, autoungrabify:true, autounselectify:true, boxSelectionEnabled:false});
  const plane = document.createElement("div");
  plane.className = "case-graph-plane";
  host.append(plane);
  const matches = new Set(slice.matches);
  for (const n of slice.nodes) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "case-graph-node";
    card.dataset.kind = n.kind;
    card.dataset.action = "map-node";
    card.dataset.id = n.id;
    card.title = n.type + " · " + n.label;
    card.setAttribute("aria-label", "Inspect " + n.type + " · " + n.label);
    const type = document.createElement("span"), label = document.createElement("strong");
    type.textContent = n.type + (n.sourceIds?.size > 1 ? ` · ${n.sourceIds.size} copies` :
      n.hypotheses?.length ? ` · ${n.hypotheses.length} ${n.hypotheses.length === 1 ? "hypothesis" : "hypotheses"}` : "");
    if (matches.has(n.id)) {
      type.textContent += " · Search match";
      card.classList.add("is-match");
      card.setAttribute("aria-description", "Search match");
    }
    const at = n.type === "Email address" ? n.label.indexOf("@") : -1;
    if (at > 0) label.append(n.label.slice(0,at), document.createElement("wbr"), n.label.slice(at));
    else label.textContent = n.label;
    card.append(type, label);
    plane.append(card);
    cards.set(n.id, card);
  }
  cy.batch(() => {
    for (const [id, card] of cards) cy.getElementById(id).data({width:card.offsetWidth, height:card.offsetHeight});
  });
  const scale = document.getElementById("case-graph-scale");
  const minimap = document.getElementById("case-graph-minimap");
  let bounds, direction, miniScale, miniX, miniY, frame;
  function camera() {
    const pan = cy.pan(), zoom = cy.zoom();
    plane.style.transform = `translate(${pan.x}px,${pan.y}px) scale(${zoom})`;
    scale.textContent = Math.round(zoom * 100) + "%";
    if (!bounds || frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const extent = cy.extent(), w = minimap.width, h = minimap.height;
      minimap.hidden = slice.nodes.length < 2 || (extent.x1 <= bounds.x1 && extent.y1 <= bounds.y1 && extent.x2 >= bounds.x2 && extent.y2 >= bounds.y2);
      if (minimap.hidden) return;
      const ctx = minimap.getContext("2d");
      miniScale = Math.min((w-12)/bounds.w, (h-12)/bounds.h);
      miniX = (w-bounds.w*miniScale)/2 - bounds.x1*miniScale;
      miniY = (h-bounds.h*miniScale)/2 - bounds.y1*miniScale;
      ctx.clearRect(0,0,w,h);
      ctx.fillStyle = theme.matches ? "#999ba8" : "#a1a5b3";
      for (const n of cy.nodes()) {
        const {x,y} = n.position(), {width,height} = n.data();
        ctx.fillRect(miniX+(x-width/2)*miniScale, miniY+(y-height/2)*miniScale, width*miniScale, height*miniScale);
      }
      ctx.strokeStyle = theme.matches ? "#c4b5fd" : "#6d58a5";
      ctx.lineWidth = 2;
      const x = Math.max(1,miniX+extent.x1*miniScale), y = Math.max(1,miniY+extent.y1*miniScale);
      ctx.strokeRect(x,y,Math.min(w-1,miniX+extent.x2*miniScale)-x,Math.min(h-1,miniY+extent.y2*miniScale)-y);
    });
  }
  minimap.addEventListener("click", event => {
    if (!miniScale) return;
    const rect = minimap.getBoundingClientRect();
    const x = ((event.clientX-rect.left)*minimap.width/rect.width-miniX)/miniScale;
    const y = ((event.clientY-rect.top)*minimap.height/rect.height-miniY)/miniScale;
    cy.pan({x:cy.width()/2-x*cy.zoom(), y:cy.height()/2-y*cy.zoom()});
  });
  function layout() {
    const narrow = host.clientWidth < 620;
    direction = narrow ? "TB" : "LR";
    cy.layout({name:"dagre", rankDir:direction, align:narrow ? "UL" : undefined, nodeSep:narrow ? 22 : 18,
      rankSep:narrow ? 44 : 68, edgeSep:12, ranker:"network-simplex", fit:false, animate:false,
      useDagreEdgeControlPoints:true, automaticDagreEdgeStyle:false}).run();
    cy.batch(() => routeCaseGraphEdges(cy, narrow));
    for (const [id, card] of cards) {
      const item = cy.getElementById(id), {x,y} = item.position(), {width,height} = item.data();
      card.style.left = (x-width/2) + "px";
      card.style.top = (y-height/2) + "px";
    }
    bounds = cy.elements().boundingBox({includeLabels:false});
    cy.fit(cy.elements(), 28);
    if (cy.zoom() > 1.1) { cy.zoom(1.1); cy.center(); }
    else if (cy.zoom() < .72) {
      cy.zoom(.82);
      const entry = cy.getElementById(page.slice.matches[0] || state.mapFocus || page.model.goal);
      if (entry.length) {
        const {x,y} = entry.position();
        cy.pan({x:(narrow ? cy.width()/2 : 114)-x*cy.zoom(), y:(narrow ? 82 : cy.height()/2)-y*cy.zoom()});
      }
    }
    camera();
  }
  cy.on("viewport", camera);
  cy.on("mouseover", "edge", event => event.target.addClass("is-hovered"));
  cy.on("mouseout", "edge", event => event.target.removeClass("is-hovered"));
  cy.on("tap", "edge", event => goto({mapEdge:event.target.id(), mapSelection:"", mapTrace:false}));
  cy.on("tap", event => { if (event.target === cy && (state.mapEdge || state.mapSelection)) goto({mapSelection:"", mapEdge:"", mapTrace:false}); });
  plane.addEventListener("focusin", event => {
    const item = event.target.closest(".case-graph-node");
    if (!item || !item.matches(":focus-visible")) return;
    const box = item.getBoundingClientRect(), outer = host.getBoundingClientRect();
    if (box.left < outer.left || box.right > outer.right || box.top < outer.top || box.bottom > outer.bottom) cy.center(cy.getElementById(item.dataset.id));
  });
  layout();
  const size = new ResizeObserver(() => {
    cy.resize();
    if ((host.clientWidth < 620 ? "TB" : "LR") !== direction) layout();
    else camera();
  });
  size.observe(host);
  const setTheme = () => { cy.style(styles()); layout(); };
  theme.addEventListener("change", setTheme);
  page.dispose = () => {
    size.disconnect();
    theme.removeEventListener("change", setTheme);
    cancelAnimationFrame(frame);
    cy.destroy();
  };
  caseGraphSelection();
}

document.addEventListener("click", event => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const {action, id} = target.dataset;
  if (action === "map-node") goto({mapSelection:id, mapEdge:"", mapTrace:false});
  else if (action === "map-edge") goto({mapEdge:id, mapSelection:"", mapTrace:false});
  else if (action === "map-trace") goto({mapSelection:id, mapEdge:"", mapTrace:!state.mapTrace});
  else if (action === "map-hypotheses") goto({mapHypotheses:!state.mapHypotheses, mapSelection:"", mapEdge:"", mapTrace:false});
  else if (action === "map-search-clear") goto({mapQuery:"", mapSelection:"", mapEdge:"", mapTrace:false});
  else if (action === "map-more") goto({mapLimit:Math.min(160, (Number(state.mapLimit) || 32) + 32)});
  else if (action === "map-zoom") caseGraphZoom(id);
});
document.addEventListener("change", event => {
  if (event.target.id === "case-graph-branch") goto({mapFocus:event.target.value, mapQuery:"", mapSelection:"", mapEdge:"", mapTrace:false, mapLimit:32});
});
document.addEventListener("submit", event => {
  if (event.target.id !== "case-graph-search") return;
  event.preventDefault();
  goto({mapQuery:document.getElementById("case-graph-query").value.trim(), mapSelection:"", mapEdge:"", mapTrace:false, mapLimit:32});
});
document.addEventListener("keydown", event => {
  if (!event.target.matches(".case-graph-stage") || !caseGraphPage?.cy) return;
  const zoom = {"+":"in", "=":"in", "-":"out", Home:"fit"}[event.key];
  const pan = {ArrowLeft:[50,0], ArrowRight:[-50,0], ArrowUp:[0,50], ArrowDown:[0,-50]}[event.key];
  if (zoom || pan) event.preventDefault();
  if (zoom) caseGraphZoom(zoom);
  if (pan) caseGraphPage.cy.panBy({x:pan[0], y:pan[1]});
});
