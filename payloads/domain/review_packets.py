"""Complete, authorized context and source-bound accounting checks for reviewers."""
from dataclasses import asdict
import hashlib
import re
from decimal import Decimal

from mn_sdk_rag import EvidenceSpan
from .financial_review import build as reconcile
from .evidence.assistant import EvidenceAssistant


def counter_query(hypothesis, matter):
    question = hypothesis['question']
    if re.search(r'authori[sz]|approv', question, re.I):
        terms = 'limited approval denied exception emergency telephone'
    elif re.search(r'loss|settle|payment|transfer|revers', question, re.I):
        terms = 'reversal reversed refund net bank reconciliation'
    else:
        terms = 'correction denial alternative contradiction'
    return ' '.join([*matter.get('transaction_refs', []), question, terms])[:4000]


def reread_leads(leads, documents, flags, records):
    """Hydrate planned locations from cleared originals, preserving each dependency group."""
    sources = {d.source_id: d for d in documents if d.text is not None and d.source_id not in flags}
    found = {p['evidence_id'] for r in records for p in r['result'].get('passages', [])}
    passages, groups = {}, []
    for refs in leads:
        if not refs or any(ref['source_id'] not in sources for ref in refs):
            continue
        component = {}
        for ref in refs:
            doc = sources[ref['source_id']]
            start, end = ref['start_offset'], ref['end_offset']
            if doc.content_sha256 != ref['content_sha256'] or not 0 <= start < end <= len(doc.text):
                raise ValueError('Planning lead no longer matches its frozen source')
            eid = hashlib.sha256(f'{doc.source_id}|{doc.content_sha256}|{start}|{end}'.encode()).hexdigest()[:32]
            component[eid] = {**ref, 'evidence_id': eid, 'text': doc.text[start:end]}
        if len(component) == 1 and component.keys() <= found:
            continue
        passages.update(component)
        groups.append({'id': f'lead-{len(groups)}', 'source_evidence_ids': list(component), 'complete': True})
    return {'purpose': 'planning_source', 'action': {'operation': 'reread_frozen_planning_sources'},
            'result': {'passages': list(passages.values()), 'support_groups': groups,
                       'status': 'selected_sources', 'exhaustive': False}}


def supplement(documents, flags, matter, records, byte_limit):
    """Use complete small corpora; otherwise expand only selected short sources.

    Discovery is not review. All candidates still pass whole-component admission.
    No quoted source is shortened and no flagged text enters this packet.
    """
    allowed = [d for d in documents if d.text and d.source_id not in flags]
    financial = reconcile(matter, documents, flags)
    selected = {p['source_id'] for r in records for p in r['result'].get('passages', [])}
    small_corpus = sum(len(d.text.encode()) + 512 for d in allowed) <= byte_limit
    candidates = [d for d in allowed if small_corpus or
                  (d.source_id in selected and len(d.text.encode()) <= 8192)]
    passages = list(financial['evidence'])
    for d in candidates:
        end = len(d.text)
        identity = hashlib.sha256(f'{d.source_id}|{d.content_sha256}|0|{end}'.encode()).hexdigest()[:32]
        passages.append({'evidence_id': identity, 'source_id': d.source_id,
            'content_sha256': d.content_sha256, 'start_offset': 0, 'end_offset': end, 'text': d.text})
    existing = {p['evidence_id'] for r in records for p in r['result'].get('passages', [])}
    passages = list({p['evidence_id']:p for p in passages if p['evidence_id'] not in existing}.values())
    return {'purpose': 'source_context', 'action': {'operation': 'complete_authorized_sources'},
        'result': {'passages': passages, 'status': 'complete' if small_corpus else 'selected_sources',
            'exhaustive': small_corpus,
            'qualification': 'Candidates for admission, not evidence of actual model or attorney review'}}, financial


def register(store, investigation_id, documents, records):
    sources = {d.source_id:d for d in documents}
    for record in records:
        for p in record['result'].get('passages', []):
            value = EvidenceSpan(**{k:v for k,v in p.items() if k != 'provenance_kind'}, provenance_kind='observed')
            EvidenceAssistant._validate_evidence(value, sources)
            store.add_evidence(investigation_id, value)


def visible_financial(financial, evidence):
    ids = {p['evidence_id'] for p in evidence}
    events = [{k:e[k] for k in ('record_id','event_type','amount','currency','transaction_ref','evidence_ids')}
              for e in financial['events'] if set(e['evidence_ids']) <= ids]
    transactions = [{k:v for k,v in t.items() if k != 'qualification'}
                    for t in financial['transactions'] if set(t['evidence_ids']) <= ids]
    return {'events': events, 'transactions': transactions,
        'omitted_event_count': len(financial['events']) - len(events),
        'qualification': 'Source quotations/numbers verified; event classifications are counsel annotations. Ledger net is not bank settlement or damages.'}


def packet_coverage(evidence, documents, admission=None):
    spans = [asdict(e) if not isinstance(e, dict) else e for e in evidence]
    complete = [d.source_id for d in documents if d.text is not None and any(
        p['source_id'] == d.source_id and p['start_offset'] == 0 and p['end_offset'] == len(d.text) for p in spans)]
    limitations = {k: admission[k] for k in ('unresolved_groups', 'unavailable_graph_paths')
                   if admission and admission.get(k)}
    return {**({'unverified_support': limitations} if limitations else {}),
        'admitted_evidence_ids': [e['evidence_id'] for e in spans],
        'admitted_source_ids': sorted({e['source_id'] for e in spans}),
        'complete_source_ids': complete,
        'definition': 'Exact sources admitted to this model request; not a completeness or accuracy certificate'}


def consistency_checks(report, financial):
    """Narrow deterministic guard for explicit absence claims, not semantic proof."""
    topics = {'approved': r'written (?:approval|authori[sz]ation)|approval (?:email|record)',
              'posting': r'ledger|posting', 'reversal': r'reversal|reversed', 'net_balance': r'ledger|net balance'}
    checks = []
    for finding in report['findings']:
        for transaction in financial.get('transactions', []):
            if transaction['net_matches_recorded'] is False:
                checks.append({'finding_id':finding['id'], 'status':'needs_review',
                    'evidence_ids':transaction['evidence_ids'],
                    'reason':'Posting/reversal arithmetic differs from a recorded net in the counsel-labelled group; reconcile the records before accepting the finding.'})
        text = finding['title'] + '. ' + finding['assessment'] + '. ' + finding['limitations']
        for event in financial['events']:
            topic = topics.get(event['event_type'])
            if not topic:
                continue
            absence = rf'\b(?:no|without)\b[^.\n]{{0,70}}\b(?:{topic})\b|\b(?:{topic})\b[^.\n]{{0,50}}\b(?:unavailable|absent|missing|not (?:visible|supplied|provided))\b'
            matches = [s for s in re.split(r'(?<=[.!?])\s+', text) if re.search(absence, s, re.I)]
            if event['event_type'] == 'approved':
                # Approval for one amount does not rebut the absence of approval
                # for a different amount. Leave that question to semantic review.
                matches = [s for s in matches if not (amounts := re.findall(r'(?:USD\s*|\$)([\d,]+(?:\.\d+)?)', s, re.I))
                           or Decimal(event['amount']) in {Decimal(a.replace(',', '')) for a in amounts}]
            if matches:
                checks.append({'finding_id':finding['id'], 'record_id':event['record_id'],
                    'status':'needs_review', 'evidence_ids':event['evidence_ids'],
                    'reason':'Possible absence claim conflicts with an available source-bound transaction record; withheld pending correction.'})
    return checks
