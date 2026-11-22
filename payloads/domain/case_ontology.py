"""Materialize the verified review as a frozen, typed DuckDB property graph."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from .workspace_case_map import add_document, case_map


PATH = 'case/case_graph.duckdb'
VERSION = 'mn.litigation.case_ontology.v1'
RELATIONS = {
    'Confirmed identity': ('CONFIRMED_ALIAS_OF', 'alias', {'person'}, 'counsel_annotation'),
    'Quoted passage': ('QUOTES', 'fact', {'document'}, 'counsel_annotation'),
    'Element support': ('SUPPORTED_BY_FACT', 'element', {'fact'}, 'counsel_annotation'),
    'Element contrary': ('CONTESTED_BY_FACT', 'element', {'fact'}, 'counsel_annotation'),
    'Element context': ('CONTEXT_FACT', 'element', {'fact'}, 'counsel_annotation'),
    'From header': ('FROM_HEADER', 'correspondent', {'communication'}, 'observed_header'),
    'To header': ('TO_HEADER', 'communication', {'correspondent'}, 'observed_header'),
    'Cc header': ('CC_HEADER', 'communication', {'correspondent'}, 'observed_header'),
    'Bcc header': ('BCC_HEADER', 'communication', {'correspondent'}, 'observed_header'),
    'Supporting citation': ('CITES_IN_SUPPORT', 'finding', {'document', 'communication'}, 'draft_assessment'),
    'Contrary citation': ('CITES_IN_CONFLICT', 'finding', {'document', 'communication'}, 'draft_assessment'),
    'Recorded reference': ('REFERENCES_TRANSACTION', 'financial_record', {'transaction'}, 'counsel_annotation'),
    'Same source': ('SAME_SOURCE', 'communication', {'financial_record'}, 'shared_source'),
    'Recorded in document': ('RECORDED_IN', 'financial_record', {'document'}, 'counsel_annotation'),
    'Examined in draft': ('EXAMINED_IN', 'issue', {'finding'}, 'draft_assessment'),
}
RELATION_CODES = tuple(spec[0] for spec in RELATIONS.values())
SCHEMA = '''
    CREATE TABLE graph_snapshot (version VARCHAR, snapshot_id VARCHAR, scope VARCHAR);
    CREATE TABLE graph_nodes (
        id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, label VARCHAR NOT NULL,
        detail VARCHAR, event_date VARCHAR, date_basis VARCHAR, qualification VARCHAR NOT NULL
    );
    CREATE TABLE graph_edges (
        id VARCHAR PRIMARY KEY, source VARCHAR NOT NULL REFERENCES graph_nodes(id),
        target VARCHAR NOT NULL REFERENCES graph_nodes(id), relation VARCHAR NOT NULL,
        label VARCHAR NOT NULL, provenance VARCHAR NOT NULL, qualification VARCHAR NOT NULL
    );
    CREATE TABLE graph_passages (
        id VARCHAR PRIMARY KEY, source_id VARCHAR NOT NULL, document VARCHAR NOT NULL,
        sha256 VARCHAR NOT NULL, start_char BIGINT NOT NULL, end_char BIGINT NOT NULL,
        CHECK (0 <= start_char AND start_char < end_char)
    );
    CREATE TABLE graph_citations (
        edge_id VARCHAR REFERENCES graph_edges(id), passage_id VARCHAR REFERENCES graph_passages(id),
        PRIMARY KEY (edge_id, passage_id)
    );
'''


def connect(path, *, read_only=False):
    return duckdb.connect(str(path), read_only=read_only, config={
        'enable_external_access': 'false', 'threads': '1'})


def publish(run_dir, workspace):
    graph = case_map(workspace, for_display=False)
    nodes = {node['id']: node for node in graph['nodes']}
    sources = {source['source_id']: source for source in workspace['sources']}
    evidence = {passage['evidence_id']: passage for passage in workspace['evidence']}
    mapped_emails = {source_id for node in nodes.values() if node['kind'] == 'communication'
                     for source_id in node['source_ids']}
    for source_id, source in sources.items():
        if source_id not in mapped_emails:
            add_document(nodes, source)

    edges, citations, passages = {}, [], {}
    for edge in graph['edges']:
        relation, from_kind, to_kinds, provenance = RELATIONS[edge['label']]
        source, target = edge['source'], edge['target']
        ids = sorted(set(edge['evidence_ids']))
        if nodes[source]['kind'] != from_kind or nodes[target]['kind'] not in to_kinds or not ids:
            raise ValueError('Invalid case graph relationship or missing source support')
        key = hashlib.sha256(json.dumps([source, relation, target, ids]).encode()).hexdigest()
        if key in edges:
            continue
        edges[key] = (key, source, target, relation, edge['label'], provenance, edge['qualification'])
        for eid in ids:
            passage = evidence[eid]
            document = sources[passage['source_id']]
            passages[eid] = (eid, passage['source_id'], document['relative_path'], passage['content_sha256'],
                             passage['start_offset'], passage['end_offset'])
            citations.append((key, eid))

    path = Path(run_dir) / PATH
    with TemporaryDirectory(prefix='.case-graph-', dir=path.parent) as temporary:
        pending = Path(temporary) / path.name
        with connect(pending) as database:
            database.begin()
            database.execute(SCHEMA)
            database.execute('INSERT INTO graph_snapshot VALUES (?, ?, ?)',
                             [VERSION, workspace['snapshot_id'], workspace['access_scope']])
            write_rows(database, 'graph_nodes', [
                (n['id'], n['kind'], n['label'], n.get('detail'), n.get('date'), n.get('date_label'), n['qualification'])
                for n in nodes.values()])
            write_rows(database, 'graph_edges', list(edges.values()))
            write_rows(database, 'graph_passages', list(passages.values()))
            write_rows(database, 'graph_citations', citations)
            from .casework_index import populate
            populate(database, workspace, nodes)
            database.commit()
        pending.replace(path)
    return {'path': PATH, 'version': VERSION, 'snapshot_id': workspace['snapshot_id'],
            'captured_at': workspace.get('captured_at'), 'sample': bool(workspace.get('sample')),
            'nodes': len(nodes), 'relationships': len(edges), 'passages': len(passages)}


def write_rows(database, table, values):
    # Bind batches as columns to avoid a SQL execution for every object and edge.
    for start in range(0, len(values), 1024):
        columns = [list(column) for column in zip(*values[start:start + 1024], strict=True)]
        projection = ', '.join('unnest(?)' for _ in columns)
        database.execute(f'INSERT INTO {table} SELECT {projection}', columns)


def rows(database, statement, parameters=()):
    result = database.execute(statement, parameters)
    columns = [field[0] for field in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


EDGE_ROWS = '''
    SELECT e.*, a.label AS from_label, b.label AS to_label
    FROM graph_edges e JOIN graph_nodes a ON a.id = e.source JOIN graph_nodes b ON b.id = e.target
'''


def passage_refs(database, edge_ids, *, per_edge):
    if not edge_ids:
        return []
    return rows(database, '''
        SELECT c.edge_id, p.*, count(*) OVER (PARTITION BY c.edge_id) AS passage_count
        FROM graph_citations c JOIN graph_passages p ON p.id = c.passage_id
        WHERE c.edge_id IN (SELECT unnest(?::VARCHAR[]))
        QUALIFY row_number() OVER (PARTITION BY c.edge_id ORDER BY p.document, p.start_char, p.id) <= ?
        ORDER BY c.edge_id, p.document, p.start_char, p.id
    ''', [list(edge_ids), per_edge])


def appendix(run_dir, graph):
    """Publish a bounded graph-query result to the existing Membrane report corpus."""
    from .review_products import escaped

    with connect(Path(run_dir) / PATH, read_only=True) as database:
        selected = rows(database, f'''
            SELECT * FROM ({EDGE_ROWS})
            QUALIFY row_number() OVER (PARTITION BY relation ORDER BY from_label, to_label, id) <= 16
            ORDER BY relation, from_label, to_label, id
        ''')
        refs = passage_refs(database, [edge['id'] for edge in selected], per_edge=2)
    by_edge = {}
    for ref in refs:
        by_edge.setdefault(ref['edge_id'], []).append(ref)
    lines = ['## Case graph', '']
    if graph.get('sample'):
        lines += ['Synthetic test matter.', '']
    if graph.get('captured_at'):
        lines += ['Snapshot captured ' + escaped(graph['captured_at']) + '.', '']
    lines += [f"The saved case ontology contains {graph['nodes']} objects and {graph['relationships']} relationships. "
             f"This appendix shows {len(selected)} relationships sampled from the authorized snapshot.", '',
             'Email links describe addressing. Financial classifications come from counsel. Finding links describe draft citation roles.', '']
    for edge in selected:
        lines += [f"### {escaped(edge['from_label'][:180])} → {escaped(edge['to_label'][:180])}", '',
                  edge['label'] + '. ' + escaped(edge['qualification'][:400]), '']
        for passage in by_edge[edge['id']]:
            lines.append(f"- {escaped(passage['document'][:240])}, normalized characters "
                         f"{passage['start_char']}–{passage['end_char']} (passage {passage['id']}).")
        lines.append('')
    return '\n'.join(lines)
