"""Bounded evidence collection and separate hypothesis/review specialists."""

from mn_sdk.blueprint.hooks import activity_operation
from dataclasses import asdict
from copy import deepcopy
from datetime import datetime, timezone
import json
from itertools import zip_longest
from mn_sdk.blueprint.context import source_manifest
from mn_graph_analysis_skill import ensure_bounded_readonly_rgql
from . import enquiry_review, search_memory
from .round_state import task_input, read, save, checkpoint
from .round_model import complete, evidence_room, guidance_for
from .handling import cleared_observation
from .assessment_citations import keys_for
from .graph_queries import QUERIES
from .indexing import validate_indexes
from .evidence.store import EvidenceStore
from .app.skill_bindings import bind_skills, DOC, GRAPH
from .app.activity import observe_action
from .app.planning import object_schema, HYPOTHESIS, validate
from .app.findings import CITATION_BYTE_LIMIT, REPORT, REVIEW, submit_report, review_report
from .app.prompt_context import investigation_history
from .review_packets import supplement, register, reread_leads, visible_financial, packet_coverage, consistency_checks, counter_query


def validate_graph_query(query):
    return ensure_bounded_readonly_rgql(query, max_limit=50)


def source_passage(evidence):
    # Other question branches can raise a passage's best search score. The
    # question's committed searches supply its rank, including during replay.
    passage = asdict(evidence)
    del passage["relevance_score"]
    return passage


def assessment_schema(task, evidence_ids, citable_ids=None):
    citation = {"$ref": "#/$defs/passage"} if evidence_ids else {"type": "string"}
    work_item = object_schema({"question": {"type": "string", "minLength": 1, "maxLength": 500},
        "requested_record": {"type": "string", "minLength": 1, "maxLength": 500},
        "why_it_matters": {"type": "string", "minLength": 1, "maxLength": 300},
        "closure_condition": {"type": "string", "minLength": 1, "maxLength": 300},
        "priority": {"enum": ["High", "Medium", "Low"]},
        "priority_basis": {"type": "string", "minLength": 1, "maxLength": 250},
        "evidence_ids": {"type": "array", "maxItems": 3, "minItems": 1,
                         "items": citation}})
    schema = deepcopy(object_schema({"hypothesis": HYPOTHESIS, "report": REPORT,
        "work_items": {"type": "array", "maxItems": 1 if evidence_ids else 0, "items": work_item}}))
    hypothesis = schema["properties"]["hypothesis"]["properties"]
    report = schema["properties"]["report"]["properties"]
    hypothesis["id"] = {"const": task["hypothesis"]["id"]}
    hypothesis["parent_id"] = {"type": "null"}
    finding = report["findings"]["items"]["properties"]
    finding["id"] = {"const": task["prefix"]}
    finding["assessment"] = {**finding["assessment"], "maxLength": 600}
    for name in ("factual_basis", "assessment"):
        hypothesis[name] = {**hypothesis[name], "maxLength": 500}
    for parent, name in ((hypothesis, "alternatives"), (hypothesis, "outstanding_enquiries"), (report, "follow_up")):
        parent[name] = {**parent[name], "maxItems": 2, "items": {"type": "string", "minLength": 1, "maxLength": 300}}
    report["conclusion_ids"] = {**report["conclusion_ids"], "maxItems": 1, "items": {"const": task["prefix"]}}
    if evidence_ids:
        schema["$defs"] = {"passage": {"enum": sorted(evidence_ids)}}
    for parent, name in ((hypothesis, "supporting_evidence"), (hypothesis, "contradictory_evidence"), (finding, "evidence_ids")):
        field = dict(parent[name])
        if evidence_ids:
            field["items"] = citation
        else:
            field["maxItems"] = 0
        parent[name] = field
    if citable_ids is not None and citable_ids != evidence_ids and citable_ids:
        finding["evidence_ids"]["items"] = {"enum": sorted(citable_ids)}
    if not evidence_ids or citable_ids == set():
        report["findings"]["maxItems"] = 0
        report["conclusion_ids"]["maxItems"] = 0
    if not evidence_ids:
        hypothesis["status"] = {"const": "inconclusive"}
    return schema


def admit_decision(frozen, stage, instruction, base, spans, records, financial, schema_for,
                   *, collected_ids=None, graph_observations=None):
    """Charge each complete trial request, including its own citation grammar."""
    from .evidence_admission import admit, coverage
    guidance = guidance_for(frozen, stage)
    searches = [r for r in records if 'purpose' in r]
    limit = frozen['config'].get('text_memory', {}).get('max_context_bytes', 32768)

    def request(packet):
        passages = packet['evidence']
        ids = {p['evidence_id'] for p in passages}
        data = {**base, **packet, 'search_coverage': coverage(searches, ids),
                'verified_financial': visible_financial(financial, passages)}
        if collected_ids is not None:
            data['omitted_passages'] = len(collected_ids - ids)
        return data, schema_for(passages)

    def fits(data, schema):
        source_context = {k: data[k] for k in ('evidence', 'graph_paths', 'graph_observations',
                          'search_coverage', 'verified_financial') if k in data}
        return (len(json.dumps(source_context).encode()) <= limit
                and evidence_room(frozen, stage, instruction, data, schema, guidance) > 0)

    data, schema = request(admit(spans, records, limit, fits_request=lambda packet: fits(*request(packet))))
    # Graph previews are optional navigation after original source admission.
    if graph_observations and fits({**data, 'graph_observations': graph_observations}, schema):
        data['graph_observations'] = graph_observations
    return data, schema


@activity_operation('Collecting source passages', completed='Source passages collected')
def collect_evidence(context, work):
    root, frozen, task = task_input(context, work)
    name = f"case/rounds/{task['prefix']}-evidence.json"
    if (root / name).exists():
        return {"evidence": save(root, name, read(root / name))}
    case = root / "case"
    corpus, _ = validate_indexes(case, frozen["config"]["investigation"]["access_scope"])
    store = EvidenceStore(case / "evidence.sqlite3")
    runtime = bind_skills(case, corpus, store, frozen["investigation_id"],
                         [d["name"] for d in source_manifest(__file__)["skill_dependencies"]],
                         config=frozen['config'], scope=frozen['memory_scope'])
    documents = tuple(corpus.scan())
    cleared = [d for d in documents if d.source_id not in frozen["source_review_flags"]]
    records = []
    h = task["hypothesis"]
    operations = [(DOC, "search", {"query": h[p + "_query"], "top_k": frozen["config"]["investigation"]["top_k"]}, p) for p in ("support", "counter")]
    operations += [(GRAPH, "query", {"rgql": QUERIES[q]}, "graph") for q in h["graph_tools"] if q in QUERIES]
    for index, (skill, operation, arguments, purpose) in enumerate(operations):
        if skill == GRAPH:
            validate_graph_query(arguments["rgql"])
        runtime.read_skill(skill)
        action = {"name": "invoke_skill", "arguments": {"skill": skill, "operation": operation, "arguments": arguments}, "reason": h["expected_information"]}
        action_path = f"case/rounds/actions/{task['prefix']}-{index:02d}.json"
        if (root / action_path).exists():
            record = read(root / action_path)
            if record["action"] != action or "error" in record["result"]:
                raise ValueError("Committed evidence action changed or previously failed")
        else:
            def search():
                try:
                    result = observe_action(action, {"records": records + [{}]},
                                            lambda *_: runtime.invoke_case_skill(skill, operation, arguments))
                except Exception as exc:
                    save(root, action_path, {"action": action, "result": {"error": str(exc)}, "purpose": purpose})
                    raise
                return cleared_observation(result, frozen["source_review_flags"])

            result = search_memory.collect(root, frozen, arguments, search) if skill == DOC else search()
            if result.get("reused"):
                register(store, frozen["investigation_id"], cleared, [{"result": result}])
                observe_action(action, {"records": records + [{}]}, lambda *_: result)
            record = {"action": action, "result": result, "purpose": purpose}
            save(root, action_path, record)
        records.append(record)
    from .source_graph import VIEWS, walk
    from .temporal_evidence import VIEWS as TEMPORAL_VIEWS, walk as temporal_walk
    from mn_sdk_rag import EvidenceSpan
    from .evidence.assistant import EvidenceAssistant
    for view in h['graph_tools']:
        if view not in VIEWS and view not in TEMPORAL_VIEWS:
            continue
        path = f"case/rounds/actions/{task['prefix']}-source-{view}.json"
        if (root/path).exists():
            record = read(root/path)
        else:
            passages = [p for r in records for p in r['result'].get('passages', [])]
            result = (temporal_walk if view in TEMPORAL_VIEWS else walk)(case, corpus, passages, view, frozen['config'])
            record = {'action':{'view':view}, 'purpose':'graph', 'result':result}
            save(root,path,record)
        by_source = {d.source_id:d for d in documents}
        record['result'] = cleared_observation(record['result'], frozen['source_review_flags'])
        for passage in record['result']['passages']:
            evidence = EvidenceSpan(**passage, provenance_kind='observed')
            EvidenceAssistant._validate_evidence(evidence, by_source)
            store.add_evidence(frozen['investigation_id'], evidence)
        records.append(record)
    leads = reread_leads(task.get('source_leads', []), documents, frozen['source_review_flags'], records)
    if leads['result']['passages']:
        register(store, frozen['investigation_id'], documents, [leads])
        records.append(leads)
    extra, _ = supplement(documents, frozen['source_review_flags'], frozen.get('matter', {}), records,
                          frozen['config'].get('text_memory', {}).get('max_context_bytes', 32768) // 2)
    if extra['result']['passages']:
        register(store, frozen['investigation_id'], documents, [extra])
        records.append(extra)
    # Exact spans are verified against frozen source bytes before ledger admission.
    ids = list(dict.fromkeys(p["evidence_id"] for r in records for p in r["result"].get("passages", [])))
    ref = save(root, name, {"hypothesis": h, "records": records, "evidence_ids": ids})
    return {"evidence": ref}


@activity_operation('Drafting an answer from the evidence', completed='Draft answer prepared')
def assess_hypothesis(context, work):
    llm_client = context.resources.get("llm")
    root, frozen, task = task_input(context, work)
    name = f"case/rounds/{task['prefix']}-assessment.json"
    if (root / name).exists():
        from .claim_memory import publish
        publish(root, frozen, task['prefix'], read(root / name))
        return {"assessment": save(root, name, read(root / name))}
    collected = read(root / f"case/rounds/{task['prefix']}-evidence.json")
    store = EvidenceStore(root / "case/evidence.sqlite3")
    allowed = set(collected["evidence_ids"])
    # The 2000-byte limit applies to one proposed finding's citations, not all
    # evidence an assessor may inspect. Retain query rank and interleave support
    # with counterevidence before admitting whole source units.
    by_id = {e.evidence_id:e for e in store.evidence_for(frozen['investigation_id'])}
    support = [p['evidence_id'] for r in collected['records'] if r['purpose']=='support'
               for p in r['result'].get('passages', [])]
    counter = [p['evidence_id'] for r in collected['records'] if r['purpose']=='counter'
               for p in r['result'].get('passages', [])]
    ranked = list(dict.fromkeys([i for pair in zip_longest(support,counter) for i in pair if i]
                               + collected['evidence_ids']))
    spans = [source_passage(by_id[id]) for id in ranked if id in allowed
             and by_id[id].source_id not in frozen['source_review_flags']]
    instruction = (
        "Assess the committed enquiry. Write one sentence per narrative field, one ordinary alternative and one "
        "outstanding question. Put citation keys in ID fields. "
        "Use document descriptions and plain language in prose. Cite one copy of repeated source text. "
        "Keep the hypothesis ID and parent_id null. "
        "Propose one finding using finding_id when a passage supports a material fact, even if the wider question "
        "is inconclusive. Every amount, source attribution and material assertion in the finding must be supported "
        "by that finding's own evidence_ids. Narrow the finding if its citations would exceed 2000 UTF-8 bytes. "
        "Put additional context in the hypothesis. If no passage supports a finding, return "
        "findings=[] and conclusion_ids=[]. "
        "Address contrary records and coverage limits. Graph previews are navigation only. Reconcile verified_financial. "
        "Use any prior review_direction to identify what needs testing. Ground the new answer in the supplied source passages. "
        "Distinguish requests, approvals, postings, reversals, settlement, estimates and actual loss. "
        "Suggest at most one specific next record or interview in work_items. Re-read available records internally. "
        "Name the document a reviewer could request and what it would resolve. Keep absence or uniqueness "
        "claims within the passages actually examined. Use record names in follow-ups instead of tool or field names. "
        "Do not invent a custodian, assignment, deadline or completed collection.")
    from .evidence_admission import assess_admitted
    from .intake import PreparedCorpus
    documents = PreparedCorpus(root / 'case', frozen['config']['investigation']['access_scope']).scan()
    from .financial_review import build as reconcile
    financial = reconcile(frozen.get('matter', {}), documents, frozen['source_review_flags'])
    def schema_for(passages):
        return assessment_schema(task, {p['evidence_id'] for p in passages},
                                 {p['evidence_id'] for p in passages if len(p['text'].encode()) <= CITATION_BYTE_LIMIT})

    enquiry = dict(task["hypothesis"])
    if "review_direction" in task:
        enquiry["review_direction"] = task["review_direction"]
    data, schema = admit_decision(frozen, 'assess', instruction,
        {'enquiry': enquiry, 'finding_id': task['prefix'], 'graph_observations': []},
        spans, collected['records'], financial, schema_for, collected_ids=allowed,
        graph_observations=investigation_history([r for r in collected['records']
            if r['purpose'] == 'graph' and 'paths' not in r['result']], max_bytes=2000))
    visible = {e["evidence_id"] for e in data["evidence"]}
    from mn_sdk.blueprint.memory import context_requirements
    requirement = context_requirements(frozen['config'])
    quality = assess_admitted(data, collected['records']) if requirement else None
    if quality:
        save(root, f"case/rounds/{task['prefix']}-context-quality.json", quality)
    if quality and quality['action']=='insufficient_evidence':
        gaps=quality['reasons'][:40]
        value={'hypothesis':{'id':task['hypothesis']['id'],'parent_id':None,
            'question':task['hypothesis']['question'],'status':'inconclusive',
            'factual_basis':'Required source support was not available after bounded retrieval.',
            'supporting_evidence':[], 'contradictory_evidence':[],
            'alternatives':['The available packet cannot resolve the enquiry.'],
            'assessment':'Insufficient evidence; no factual finding was generated.',
            'outstanding_enquiries':gaps[:2]},
            'report':{'findings':[],'conclusion_ids':[],'follow_up':gaps[:2]}, 'work_items': []}
        validate(schema,value)
    else:
        value = complete(root, frozen, task["prefix"] + "-assess", "assess", instruction, data, schema, llm_client)
    h = value["hypothesis"]
    if h["id"] != task["hypothesis"]["id"] or h["parent_id"] is not None:
        raise ValueError("Assessment changed the committed hypothesis identity")
    h["question"] = task["hypothesis"]["question"]
    h["parent_id"] = task["hypothesis"].get("parent_id")
    value["question_origin"] = task["hypothesis"].get("origin", "Model enquiry")
    cited = set(h["supporting_evidence"] + h["contradictory_evidence"])
    cited.update(e for f in value["report"]["findings"] for e in f["evidence_ids"])
    if not cited <= visible or (h["status"] in ("supported", "contradicted") and not cited):
        raise ValueError("Assessment cites unavailable evidence")
    if any(f["id"] != task["prefix"] for f in value["report"]["findings"]):
        raise ValueError("Finding identity must match committed task")
    admitted_coverage = packet_coverage(data['evidence'], documents, data['support_admission'])
    data = {"source_review_flags": frozen["source_review_flags"]}
    submit_report(data, value["report"], store, frozen["investigation_id"])
    value["counsel_issue_ids"] = task["hypothesis"].get("counsel_issue_ids", [])
    value['evidence_review_coverage'] = admitted_coverage
    value['model_dispatched'] = not (quality and quality['action']=='insufficient_evidence')
    ref = save(root, name, value)
    from .claim_memory import publish
    publish(root, frozen, task['prefix'], value)
    return {"assessment": ref}


@activity_operation('Looking for an independent contrary record', completed='Independent counterevidence search completed')
def check_counterevidence(context, work):
    root, frozen, task = task_input(context, work)
    action_path = f"case/rounds/{task['prefix']}-review-search.json"
    if (root / action_path).exists():
        return {"counter_search": save(root, action_path, read(root / action_path))}
    corpus, _ = validate_indexes(root / 'case', frozen['config']['investigation']['access_scope'])
    store = EvidenceStore(root / 'case/evidence.sqlite3')
    runtime = bind_skills(root / 'case', corpus, store, frozen['investigation_id'],
        [d['name'] for d in source_manifest(__file__)['skill_dependencies']],
        config=frozen['config'], scope=frozen['memory_scope'])
    runtime.read_skill(DOC)
    query = counter_query(task['hypothesis'], frozen.get('matter', {}))
    result = runtime.invoke_case_skill(DOC, 'search', {'query': query, 'top_k': frozen['config']['investigation']['top_k']})
    independent = {'purpose': 'independent_counter', 'action': {'query': query},
                   'result': cleared_observation(result, frozen['source_review_flags'])}
    return {"counter_search": save(root, action_path, independent)}


@activity_operation('Checking the answer against its citations and contrary records', completed='Citation review finished')
def review_finding(context, work):
    llm_client = context.resources.get("llm")
    root, frozen, task = task_input(context, work)
    name = f"case/rounds/{task['prefix']}-review.json"
    assessment = read(root / f"case/rounds/{task['prefix']}-assessment.json")
    if (root / name).exists():
        value = read(root / name)
        ref = save(root, name, value)
        enquiry_review.publish(root, frozen, assessment, value, ref)
        return {"review": ref}
    store = EvidenceStore(root / "case/evidence.sqlite3")
    data = {"source_review_flags": frozen["source_review_flags"]}
    submit_report(data, assessment["report"], store, frozen["investigation_id"])
    direct = {i for f in assessment["report"]["findings"] for i in f["evidence_ids"]}
    cited = direct.union(assessment['hypothesis']['supporting_evidence'], assessment['hypothesis']['contradictory_evidence'])
    schema = deepcopy(REVIEW)
    finding_ids = [f["id"] for f in assessment["report"]["findings"]]
    schema["properties"]["accepted_ids"] = {"type": "array", "uniqueItems": True,
        "maxItems": len(finding_ids), "items": {"enum": finding_ids} if finding_ids else {"type": "string"}}
    from .evidence_admission import IncompleteSupport, review_closure
    from .intake import PreparedCorpus
    documents = PreparedCorpus(root / 'case', frozen['config']['investigation']['access_scope']).scan()
    collected = read(root / f"case/rounds/{task['prefix']}-evidence.json")
    records = list(collected['records'])
    action_path = f"case/rounds/{task['prefix']}-review-search.json"
    independent = read(root / action_path)
    counter_search_ref = save(root, action_path, independent)
    records.append(independent)
    extra, financial = supplement(documents, frozen['source_review_flags'], frozen.get('matter', {}), records,
        frozen['config'].get('text_memory', {}).get('max_context_bytes', 32768) // 2)
    records.append(extra)
    register(store, frozen['investigation_id'], documents, records)
    stored = {e.evidence_id: e for e in store.evidence_for(frozen['investigation_id'])
              if e.source_id not in frozen['source_review_flags']}
    independent_ids = [p['evidence_id'] for p in independent['result'].get('passages', [])]
    observed = (p['evidence_id'] for r in records for p in r['result'].get('passages', []))
    ranked = dict.fromkeys([*independent_ids, *collected['evidence_ids'], *observed, *sorted(cited)])
    all_spans = [source_passage(stored[key]) for key in ranked if key in stored]
    support_issue = None
    try:
        required = review_closure(all_spans, records, cited)
    except IncompleteSupport as exc:
        required = []
        support_issue = str(exc)
    required_ids = {p['evidence_id'] for p in required}
    spans = required + [span for span in all_spans if span['evidence_id'] not in required_ids]
    assessor_keys = keys_for(assessment.get('evidence_review_coverage', {}).get('admitted_evidence_ids', []))
    for span in spans:
        span['cited_in_finding'] = span['evidence_id'] in direct
        if span['evidence_id'] in assessor_keys:
            span['assessor_citation'] = assessor_keys[span['evidence_id']]
    if required:
        records.append({'result':{'support_groups':[{'id':'review-cited', 'complete':True, 'required':True,
            'source_evidence_ids':[p['evidence_id'] for p in required]}]}})
    if financial['events'] and finding_ids:
        schema['properties']['financial_checks'] = {'type':'array', 'minItems':len(finding_ids),
            'maxItems':len(finding_ids), 'items':object_schema({
                'finding_id':{'enum':finding_ids}, 'status':{'enum':['consistent','contradiction','unresolved']},
                'record_ids':{'type':'array', 'uniqueItems':True, 'items':{'enum':sorted({e['record_id'] for e in financial['events']})}},
                'reason':{'type':'string', 'minLength':1, 'maxLength':1000}})}
        schema['required'].append('financial_checks')
    instruction = (
        "First check the proposed finding using only passages marked cited_in_finding=true. Check each amount, "
        "date, attribution and material assertion. If any needs another passage, reject the finding even if that "
        "passage appears elsewhere in this packet. Explain the missing citation. Then check supplied dependencies, "
        "the independent counter-search and verified_financial for challenges. "
        "Reject claims that available approval, ledger, posting "
        "or reversal records are absent; distinguish accounting net from bank settlement and loss. "
        "Accept only wording supported by these sources, preserving identity uncertainty, competing explanations and incomplete coverage. "
        "Reject overstatement, missing context, unsupported dates or allegations; explain issues concisely. "
        "When financial_checks is requested, return exactly one check per finding and list every supplied financial record_id. "
        "Unresolved reconciliation or contradiction requires rejection. "
        "accepted_ids must contain report finding IDs, NEVER evidence or source IDs. Return [] to reject all. You cannot add evidence or rewrite the finding.")
    packet, _ = admit_decision(frozen, 'review', instruction,
        {'report':assessment['report'], 'hypothesis':assessment['hypothesis']},
        spans, records, financial, lambda _: schema)
    conflicts = consistency_checks(assessment['report'], financial)
    dispatched = support_issue is None and required_ids <= {e['evidence_id'] for e in packet['evidence']}
    if not dispatched:
        value = {'accepted_ids':[], 'issues':[support_issue or 'Complete cited dependency packet did not fit review capacity.']}
    else:
        value = complete(root, frozen, task['prefix'] + '-review', 'review', instruction, packet, schema, llm_client)
        checks = value.pop('financial_checks', [])
        if financial['events'] and finding_ids:
            if {c['finding_id'] for c in checks} != set(finding_ids):
                raise ValueError('Financial consistency review must cover every finding exactly once')
            expected = {e['record_id'] for e in financial['events']}
            for check in checks:
                if set(check['record_ids']) != expected or packet['verified_financial']['omitted_event_count']:
                    check['status'] = 'unresolved'
                    check['reason'] = 'Financial record coverage incomplete; do not publish this finding.'
                if check['status'] != 'consistent':
                    value['accepted_ids'] = [i for i in value['accepted_ids'] if i != check['finding_id']]
            conflicts.extend(checks)
    for conflict in conflicts:
        if conflict['status'] != 'consistent':
            value['accepted_ids'] = [i for i in value['accepted_ids'] if i != conflict['finding_id']]
            value['issues'].append(conflict['reason'])
    review_report(data, value)
    value['consistency_checks'] = conflicts
    value['evidence_review_coverage'] = packet_coverage(packet['evidence'], documents, packet['support_admission'])
    value['independent_search'] = action_path
    value['model_dispatched'] = dispatched
    value['feedback'] = enquiry_review.feedback(task, assessment, value, collected, independent,
        [d for d in documents if d.source_id not in frozen['source_review_flags']])
    value['feedback']['counter_search_ref'] = counter_search_ref
    value['reviewed_at'] = datetime.now(timezone.utc).isoformat()
    ref = save(root, name, value)
    enquiry_review.publish(root, frozen, assessment, value, ref)
    return {'review': ref}


@activity_operation('Bringing the question reviews together', completed='Question reviews summarized')
def summarize_round(context, work):
    root, frozen, task = task_input(context, work)
    state = checkpoint(root, frozen)
    latest = {}
    for path in sorted((root / "case/rounds").glob("r*-review.json")):
        feedback = read(path)["feedback"]
        latest[feedback["id"]] = feedback
    findings = [{"id": h["id"], "question": h["question"], "status": h["status"],
                 "assessment": h["assessment"], "counter_evidence": h["contradictory_evidence"],
                 "outstanding_enquiries": h["outstanding_enquiries"], "feedback": latest[h["id"]]}
                for h in state["data"]["hypotheses"].values()]
    name = f"case/rounds/summary-{task['revision']:02d}.json"
    return {"summary": save(root, name, {"findings": findings, "review": state["data"]["report_review"]})}
