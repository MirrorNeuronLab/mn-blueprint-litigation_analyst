"""Select exhibits for the reading brief from the verified matter snapshot."""
import re


def source_titles(workspace):
    subjects = {source_id: event['title'] for event in workspace['temporal']['events']
                for source_id in event['source_ids'] if event.get('title')}
    titles = {}
    for source in workspace['sources']:
        key = source['source_id']
        title = subjects.get(key)
        if not title:
            # A memo can carry its own subject even when it has no email envelope.
            header = '\n'.join((source['text'] or '')[:1600].splitlines()[:12])
            subject = re.search(r'^Subject:[ \t]*([^\r\n]+)', header, re.I | re.M)
            title = subject[1].strip() if subject else ''
        titles[key] = title or source['relative_path'].rsplit('/', 1)[-1]
    return titles


def excerpt(text, question):
    """Choose a complete paragraph or list item. The full cited span stays attached."""
    terms = set(re.findall(r'\d+(?:\.\d+)?|[^\W\d_]{3,}', question.casefold()))
    terms.difference_update({'the', 'and', 'for', 'that', 'was', 'are', 'what', 'does', 'with', 'from', 'any'})
    candidates = []
    for part in re.split(r'\n[ \t]*\n|\n(?=[ \t]*(?:[-*•]|[\da-z]+[.)])[ \t]+)', text):
        part = re.sub(r'^(?:[-*•]|[\da-z]+[.)])[ \t]+', '', part.strip())
        if not part or part.endswith(':') or re.match(
                r'^(?:from|to|cc|bcc|date|subject|message-id|received|mime-version):', part, re.I):
            continue
        words = set(re.findall(r'\d+(?:\.\d+)?|[^\W\d_]{3,}', part.casefold()))
        score = sum(3 if word[0].isdigit() else 1 for word in terms & words)
        candidates.append((score, part))
    if not candidates:
        return ''
    score, best = max(candidates, key=lambda item: item[0])
    # Keep a long relevant passage behind its citation instead of clipping a
    # qualification or choosing an unrelated short line because it fits.
    return best if len(best) <= 320 and (score or len(candidates) == 1) else ''


def build(workspace):
    passages = {p['evidence_id']: p for p in workspace['evidence']}
    handoff = workspace['supervision']
    groups = [(handoff['next_review']['question'], handoff['next_review']['evidence_ids'])]
    contrary = set()
    retained = set(handoff['retained_finding_ids'])
    for finding in workspace['findings']:
        if finding['id'] in retained:
            groups.append((finding['title'], finding['supporting_evidence'] + finding.get('counter_evidence', [])))
            contrary.update(finding.get('counter_evidence', []))
    for issue in workspace.get('issues', []):
        groups.append((issue['question'], issue['supporting_evidence'] + issue['contradictory_evidence']))
        contrary.update(issue['contradictory_evidence'])
    groups.extend((gap['question'], gap['source_evidence_ids']) for gap in workspace['gaps'])
    groups.extend((event['transaction_ref'], event['evidence_ids']) for event in workspace['financial_review']['events'])

    cited = {}
    for question, ids in groups:
        for ident in ids:
            cited.setdefault(ident, question)
    # Make room for the contrary basis alongside the lead citations.
    ordered = list(cited)[:2] + [ident for ident in cited if ident in contrary] + list(cited)
    highlights, shown_versions = [], set()
    for ident in dict.fromkeys(ordered):
        passage = passages[ident]
        version = passage['content_sha256']
        if version in shown_versions:
            continue
        highlights.append({'evidence_id': ident, 'excerpt': excerpt(passage['text'], cited[ident])})
        shown_versions.add(version)
        if len(highlights) == 3:
            break
    return {'titles': source_titles(workspace), 'cited_ids': list(cited), 'highlights': highlights}
