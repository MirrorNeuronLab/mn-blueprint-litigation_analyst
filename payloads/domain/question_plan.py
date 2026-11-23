"""The editable case question list and the handoff from planning to execution."""
import re
import time

from mn_sdk.blueprint import approvals
from mn_sdk.blueprint.hooks import activity_operation, fingerprint

from .round_state import load, open_round, save

DRAFT = 'case/plan/draft.json'
REVIEW = 'case/plan/reviewed.json'
EXECUTION = 'case/plan/execution.json'
LINE = re.compile(r'^\s*(?:(\d+)[.)]\s+|[-*]\s+)?(.+)$')


def bound(root, reference, path):
    if not isinstance(reference, dict) or reference.get('path') != path:
        raise ValueError('The question plan reference belongs to a different stage')
    return load(root, reference)


@activity_operation('Drafting investigation questions', completed='Investigation questions drafted')
def draft_questions(block, inputs):
    from .round_planning import propose
    reference = inputs['previous']['result']['context']
    root, frozen = open_round(block, reference)
    if (root / 'case/cancel.request').exists():
        proposal, overview = {'decision': 'stop', 'rationale': 'cancelled', 'hypotheses': []}, {}
    else:
        proposal, overview = propose(block, root, frozen, 0)
    return {'draft': save(root, DRAFT, {'context': reference, 'proposal': proposal, 'source_overview': overview})}


def question_key(text):
    return ' '.join(text.casefold().split())


def free_id(used):
    return next(f'H{n:02d}' for n in range(1, 100) if f'H{n:02d}' not in used)


def edited_questions(text, proposed, maximum):
    """Numbered lines keep the proposal's identity even when reordered or edited."""
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 8000:
        raise ValueError('Enter at least one question and keep the list under 8 KB.')
    originals = {question_key(h['question']): h for h in proposed}
    used = {h['id'] for h in proposed}
    result, seen, assigned = [], set(), set()
    for line in text.splitlines():
        if not line.strip():
            continue
        match = LINE.fullmatch(line.strip())
        number, wording = match.groups()
        wording = wording.strip()
        key = question_key(wording)
        if not wording or re.fullmatch(r'\d+[.)]|[-*]', wording) or len(wording) > 500 or key in seen:
            raise ValueError('Use distinct questions of up to 500 characters each, one per line.')
        numbered = int(number) if number and len(number) <= 2 else 0
        original = proposed[numbered - 1] if 1 <= numbered <= len(proposed) else originals.get(key)
        ident = original['id'] if original else free_id(used)
        if ident in assigned:
            raise ValueError('Use each question number once. Add new questions on their own lines.')
        origin = 'Added in Chat' if not original else ('Reviewed plan' if wording == original['question'] else 'Edited in Chat')
        result.append({'id': ident, 'question': wording, 'origin': origin})
        seen.add(key)
        used.add(ident)
        assigned.add(ident)
        if len(result) > maximum:
            raise ValueError(f'This run can investigate up to {maximum} initial questions. Shorten the list and submit it again.')
    return result


@activity_operation('Waiting for your question plan in Chat', completed='Question plan review finished')
def review_questions(block, inputs):
    draft_ref = inputs['previous']['result']['draft']
    root = block.store.run_dir
    draft = bound(root, draft_ref, DRAFT)
    _, frozen = open_round(block, draft['context'])
    proposed = draft['proposal']['hypotheses']

    def receipt(status, questions, decision=None):
        record = {'version': 'mn.litigation.question_plan.v1', 'draft': draft_ref,
                  'status': status, 'questions': questions}
        if decision:
            record['request_id'] = decision['payload']['request_id']
        reviewed = save(root, REVIEW, record)
        if decision and decision['type'] != 'human_decision_applied':
            approvals.publish_human_interaction_event(block.run_id, 'human_decision_applied',
                                                      {'request_id': record['request_id']})
        return {'reviewed': reviewed}

    if (root / 'case/cancel.request').exists() or draft['proposal']['rationale'] == 'cancelled':
        return receipt('cancelled', [])
    if not proposed and draft['proposal']['rationale'] == 'no_authorized_readable_sources':
        return receipt('no_sources', [])
    if not proposed:
        raise ValueError('The investigation needs at least one proposed question')
    maximum = frozen['review_plan']['max_review_questions']
    window = block.freeze_checkpoint('case/plan/review-window.json',
                                     lambda: {'expires_at': int((time.time() + 86400) * 1000)})
    expires = block.read_checkpoint(window, expected_path='case/plan/review-window.json')['expires_at']
    initial = '\n'.join(f"{n}. {h['question']}" for n, h in enumerate(proposed, 1))
    attempt, correction, editable = 0, '', initial
    while True:
        block.check()
        request_id = 'case-plan-' + fingerprint([block.run_id, draft_ref, attempt])
        prompt = (f'{initial}\n\nEdit or remove a question, or add one on a new line. Choose Start investigation when ready. '
                  f'This run can take up to {maximum} questions.')
        if correction:
            prompt += '\n\n' + correction
        event = approvals.publish_human_interaction_event(block.run_id, 'human_input_requested', {
            'request_id': request_id, 'interaction_kind': 'missing_information',
            'title': 'Review investigation questions', 'message': prompt,
            'blocking': True, 'expires_at': expires, 'default_answer': {'text': editable},
            'options': [{'id': 'start', 'label': 'Start investigation', 'action': 'approve'},
                        {'id': 'cancel', 'label': 'Cancel investigation', 'action': 'reject'}]})
        if event['type'] == 'human_input_requested':
            remaining = (expires - time.time() * 1000) / 1000
            if remaining <= 0:
                raise ValueError('The question review expired before execution started.')
            try:
                event = approvals.await_human_decision(block.run_id, request_id, timeout=remaining)
            except approvals.InteractionError as error:
                if error.code != 'wait_timeout':
                    raise
                raise ValueError('The question review expired before execution started.') from error
        block.check()
        answer = event.get('payload', {})
        if event['type'] == 'human_input_timeout':
            raise ValueError('The question review closed before execution started.')
        if event['type'] not in {'human_input_received', 'human_decision_applied'} or answer.get('request_id') != request_id:
            raise ValueError('The investigation stopped before evidence work. A confirmed question list is required.')
        if answer.get('decision') == 'reject' and answer.get('approved') is False:
            return receipt('cancelled', [], event)
        if answer.get('decision') != 'approve' or answer.get('approved') is not True:
            raise ValueError('The investigation stopped before evidence work. A confirmed question list is required.')
        try:
            questions = edited_questions(answer.get('notes'), proposed, maximum)
        except ValueError as error:
            correction = str(error)
            notes = answer.get('notes')
            editable = notes if isinstance(notes, str) and 0 < len(notes.encode()) <= 8000 else initial
            attempt += 1
            continue
        return receipt('reviewed', questions, event)


@activity_operation('Preparing evidence searches for the reviewed questions', completed='Evidence searches prepared')
def start_execution(block, inputs):
    from .round_planning import reviewed_searches
    root = block.store.run_dir
    reviewed_ref = inputs['previous']['result']['reviewed']
    review = bound(root, reviewed_ref, REVIEW)
    draft = bound(root, review['draft'], DRAFT)
    reference = draft['context']
    _, frozen = open_round(block, reference)
    proposal = draft['proposal']
    if review['status'] == 'reviewed' and review['questions']:
        proposal = {**proposal, 'hypotheses': reviewed_searches(block, root, frozen, draft, review['questions'])}
    elif review['status'] == 'cancelled':
        proposal = {'decision': 'stop', 'rationale': 'cancelled', 'hypotheses': []}
    elif review['status'] != 'no_sources' or proposal['rationale'] != 'no_authorized_readable_sources':
        raise ValueError('Execution needs the reviewed investigation plan')
    clock = block.freeze_checkpoint('case/plan/start-time.json', lambda: {'started_at': time.time()})
    started = block.read_checkpoint(clock, expected_path='case/plan/start-time.json')['started_at']
    execution = save(root, EXECUTION, {'reviewed': reviewed_ref, 'context': reference, 'proposal': proposal,
                                       'deadline': started + frozen['review_plan']['seconds']})
    return {'context': reference, 'execution': execution}


def execution_plan(root, seed, context_ref):
    binding = bound(root, seed.get('execution'), EXECUTION)
    review = bound(root, binding['reviewed'], REVIEW)
    draft = bound(root, review['draft'], DRAFT)
    if binding['context'] != context_ref or draft['context'] != context_ref:
        raise ValueError('The reviewed question list belongs to another case snapshot')
    return binding, draft, binding['proposal']


def followup_questions(candidates, earlier, reviews, proposed):
    """Branch for new wording. A repeat search retains the original question and parent."""
    prior = {q['id']: q for plan in earlier for q in plan['hypotheses']}
    by_wording = {question_key(q['question']): q for q in prior.values()}
    removed = {question_key(q['question']) for q in proposed} - by_wording.keys()
    used = set(prior).union(q['id'] for q in proposed)
    result, scheduled = [], set()
    for candidate in candidates:
        parent = candidate['id']
        if parent not in reviews:
            raise ValueError('A follow-up needs a question from the completed evidence review')
        key = question_key(candidate['question'])
        if key in scheduled or key in removed:
            continue
        previous = by_wording.get(key)
        if previous and previous['id'] != parent:
            continue
        if previous:
            question = {**candidate, **{k: previous[k] for k in ('id', 'question', 'origin')},
                        'parent_id': previous.get('parent_id')}
        else:
            question = {**candidate, 'id': free_id(used), 'parent_id': parent, 'origin': 'Follow-up'}
        result.append(question)
        used.add(question['id'])
        scheduled.add(key)
    return result


def notify_followup(block, context_ref, question, parent_question):
    identity = 'case-followup-' + fingerprint([context_ref, question['id'], question['question']])
    approvals.publish_human_interaction_event(block.run_id, 'human_notice', {
        'request_id': identity, 'notice_id': identity, 'title': 'New investigation question',
        'message': f"{question['question']}\n\n{question['expected_information']}\n\nFollow-up to “{parent_question}”",
        'blocking': False})
