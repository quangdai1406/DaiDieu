#!/usr/bin/env python3
"""Second Brain index: a local GraphRAG-style index over a folder of Markdown copies of the wiki.

It reads the Index, the Graph and Entities docs, and every page, then answers three questions:
which page is about X, what X connects to (typed edges, up to N hops), and what in the wiki is
broken. Keyword ranking only, no embeddings. Python 3, standard library only.
"""
import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict, deque
from pathlib import Path

LINK = re.compile(r'\[([^\]]+)\]\(([^)]*)\)')
WIKILINK = re.compile(r'\[\[([^\]|#]+)')
VERSION = re.compile(r'Version[:\s]+(\d{4}-\d{2}-\d{2})\s*(v\d+)?', re.I)
HEADING = re.compile(r'^(#{1,6})\s+(.*\S)\s*$')
ROW = re.compile(r'^\s*\|.*\|\s*$')
SEPARATOR = re.compile(r'^\s*\|\s*:?-')
BULLET_EDGE = re.compile(r'^\s*[-*]\s*(.+?)\s*->\s*(.+?)\s*$')
COPY_SUFFIX = re.compile(r'\s*\(\d+\)$')
WORD = re.compile(r'[a-z0-9]{2,}')
CONF_CHECK = 0.85
OUT_NAME = '.brindex'


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def base_title(stem):
    return COPY_SUFFIX.sub('', stem).strip()


def cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def tables(lines):
    """Yield (header, rows) for each Markdown table; separator rows are skipped."""
    i = 0
    while i < len(lines):
        if ROW.match(lines[i]) and i + 1 < len(lines) and SEPARATOR.match(lines[i + 1]):
            header, rows = [h.lower() for h in cells(lines[i])], []
            i += 2
            while i < len(lines) and ROW.match(lines[i]):
                rows.append(cells(lines[i]))
                i += 1
            yield header, rows
        else:
            i += 1


def field(header, row, prefix):
    for name, value in zip(header, row):
        if name.startswith(prefix):
            return value
    return ''


def split_names(text):
    return [p.strip() for p in text.split(';') if p.strip() and p.strip().lower() != 'none']


def confidence(text):
    match = re.match(r'\s*(\d(?:\.\d+)?)', text or '')
    return float(match.group(1)) if match else None


def read_page(path, root):
    text = path.read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()
    rel = path.relative_to(root).as_posix()
    stem = path.stem
    version = next((m.group(1) + (' ' + m.group(2) if m.group(2) else '')
                    for line in lines[:40] if (m := VERSION.search(line))), '')
    connections, in_block = [], False
    for line in lines:
        heading = HEADING.match(line)
        if heading:
            in_block = heading.group(2).strip().lower() == 'connections'
            continue
        if in_block and (edge := BULLET_EDGE.match(line)):
            connections.append({'relation': edge.group(1).strip(), 'name': edge.group(2).strip()})
    return {
        'id': slug(rel),
        'title': stem,
        'base_title': base_title(stem),
        'path': rel,
        'folder': rel.split('/')[0] if '/' in rel else '',
        'superseded': bool(re.search('superseded', stem, re.I)) or rel.split('/')[0].startswith('99 '),
        'version': version,
        'connections': connections,
        'wikilinks': sorted(set(WIKILINK.findall(text))),
        'text': text,
    }


def parse_index(text):
    """Return [{'area', 'title', 'url'}] for every link inside an area section (## heading)."""
    entries, area = [], None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            if len(heading.group(1)) == 2:
                area = LINK.sub(r'\1', heading.group(2)).strip()
            continue
        if area:
            for title, url in LINK.findall(line):
                entries.append({'area': area, 'title': title.strip(), 'url': url})
    return entries


def parse_graph(page, nodes, edges, dupes):
    """Node tables (ID first column) and edge tables (# | From | Relation | To ...) in a Graph doc."""
    graph = page['title']
    for header, rows in tables(page['text'].splitlines()):
        if header[0] == '#' and 'from' in header:
            for row in rows:
                if len(row) < 4 or not row[0]:
                    continue
                relation = row[2]
                possible = relation.lower().startswith('possible ')
                edges.append({
                    'graph': graph,
                    'from': row[1].strip('` '),
                    'relation': re.sub(r'^possible\s+', '', relation, flags=re.I),
                    'to': row[3].strip('` '),
                    'possible': possible,
                    'note': field(header, row, 'note'),
                    'source': field(header, row, 'source'),
                    'conf': confidence(field(header, row, 'conf')),
                })
        elif header[0] == 'id' and len(header) > 1 and header[1] in ('name', 'page title'):
            for row in rows:
                if not row[0]:
                    continue
                node_id = row[0].strip('` ')
                name = field(header, row, 'name') or field(header, row, 'page title')
                if node_id in nodes:
                    dupes.append(node_id)
                    continue
                nodes[node_id] = {
                    'id': node_id,
                    'name': name,
                    'kind': field(header, row, 'kind') or ('Page' if header[1] == 'page title' else ''),
                    'also_called': split_names(field(header, row, 'also called')),
                    'pages': split_names(field(header, row, 'page')),
                    'graph': graph,
                }


def parse_entities(page):
    """Rows of an Entities doc that carry a name and an 'Also called' column."""
    rows_out = []
    for header, rows in tables(page['text'].splitlines()):
        if 'name' in header and any(h.startswith('also called') for h in header):
            for row in rows:
                name = field(header, row, 'name')
                if name:
                    rows_out.append({'name': name, 'also_called': split_names(field(header, row, 'also called')),
                                     'doc': page['title']})
    return rows_out


def build(root, out_dir):
    root = root.resolve()
    pages, index_entries, nodes, edges, entities, dupes = [], [], {}, [], [], []
    for path in sorted(root.rglob('*.md')):
        if any(part.startswith('.') for part in path.relative_to(root).parts):
            continue
        pages.append(read_page(path, root))
    live = [p for p in pages if not p['superseded']]
    for page in live:
        stem = page['title']
        if stem.startswith('Index') and not index_entries:
            index_entries = parse_index(page['text'])
        if stem.startswith('Graph - '):
            parse_graph(page, nodes, edges, dupes)
        if stem.startswith('Entities'):
            entities.extend(parse_entities(page))
    data = {
        'built': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'root': str(root),
        'pages': [{k: v for k, v in p.items() if k != 'text'} for p in pages],
        'index': index_entries,
        'nodes': nodes,
        'edges': edges,
        'entities': entities,
        'duplicate_node_ids': dupes,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / '.gitignore').write_text('*\n', encoding='utf-8')
    (out_dir / 'index.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    texts = {p['path']: p['text'] for p in pages}
    (out_dir / 'bodies.json').write_text(json.dumps(texts, ensure_ascii=False), encoding='utf-8')
    return data


def load(root, out_dir, rebuild):
    index_file = out_dir / 'index.json'
    newest = max((p.stat().st_mtime for p in root.rglob('*.md')
                  if not any(part.startswith('.') for part in p.relative_to(root).parts)), default=0)
    if rebuild or not index_file.exists() or index_file.stat().st_mtime < newest:
        build(root, out_dir)
    return json.loads(index_file.read_text(encoding='utf-8'))


def find_nodes(data, query):
    q = query.casefold().strip()
    hits = [n for n in data['nodes'].values()
            if q == n['id'].casefold() or q == n['name'].casefold()
            or any(q == a.casefold() for a in n['also_called'])]
    return hits


def page_by_title(data, title):
    matches = [p for p in data['pages'] if not p['superseded'] and p['base_title'] == title]
    return matches[0] if matches else None


def cmd_status(data, out_dir):
    live = [p for p in data['pages'] if not p['superseded']]
    graphs = sorted({n['graph'] for n in data['nodes'].values()})
    print(f"root: {data['root']}\nbuilt: {data['built']}\nindex: {out_dir / 'index.json'}")
    print(f"pages: {len(live)} live, {len(data['pages']) - len(live)} superseded")
    print(f"index entries: {len(data['index'])}; graph docs: {len(graphs)}; "
          f"nodes: {len(data['nodes'])}; edges: {len(data['edges'])}; entity rows: {len(data['entities'])}")


def cmd_search(data, terms, limit):
    wanted = [t.casefold() for t in terms]
    bodies = json.loads((Path(data['_out']) / 'bodies.json').read_text(encoding='utf-8'))
    scored = []
    for page in data['pages']:
        if page['superseded']:
            continue
        body = bodies.get(page['path'], '').casefold()
        words = Counter(WORD.findall(body))
        title = page['title'].casefold()
        score = 0.0
        for t in wanted:
            score += (10 if t in title else 0) + min(words.get(t, 0), 5)
        if score:
            score /= 1 + math.log(1 + len(words))
            snippet = next((ln.strip()[:120] for ln in body.splitlines() if any(t in ln for t in wanted)), '')
            scored.append((score, page, snippet))
    scored.sort(key=lambda r: (-r[0], r[1]['path']))
    for score, page, snippet in scored[:limit]:
        print(f"{score:6.2f}  {page['path']}\n        {snippet}")
    if not scored:
        print('no match; try a shorter term or a name from lookup')


def cmd_lookup(data, query):
    nodes = find_nodes(data, query)
    entity_hits = [e for e in data['entities']
                   if query.casefold() in [e['name'].casefold()] + [a.casefold() for a in e['also_called']]]
    if not nodes and not entity_hits:
        print(f'no node or entity named {query!r}; check Pending in the Graph doc, then ask')
        return
    for n in nodes:
        print(f"{n['id']}  {n['name']}  [{n['kind']}]  graph: {n['graph']}")
        if n['also_called']:
            print(f"    also called: {'; '.join(n['also_called'])}")
        for p in n['pages']:
            print(f"    page: {p}")
    for e in entity_hits:
        print(f"entity row: {e['name']} (in {e['doc']}; no node)")


def cmd_neighbors(data, query, hops):
    seeds = find_nodes(data, query)
    if not seeds:
        print(f'no node named {query!r}')
        return
    valid = [e for e in data['edges'] if e['from'] in data['nodes'] and e['to'] in data['nodes']]
    adjacent = defaultdict(list)
    for e in valid:
        adjacent[e['from']].append((e, e['to'], 'out'))
        adjacent[e['to']].append((e, e['from'], 'in'))
    seen = {n['id'] for n in seeds}
    queue = deque((n['id'], 0) for n in seeds)
    while queue:
        node_id, depth = queue.popleft()
        if depth >= hops:
            continue
        for edge, other, direction in adjacent[node_id]:
            mark = ' (possible)' if edge['possible'] else ''
            check = ' check' if edge['conf'] is not None and edge['conf'] < CONF_CHECK else ''
            arrow = f"{edge['from']} -{edge['relation']}-> {edge['to']}"
            print(f"hop {depth + 1}: {arrow}{mark} conf {edge['conf']}{check}")
            if other not in seen:
                seen.add(other)
                queue.append((other, depth + 1))
    print('pages:')
    for node_id in sorted(seen):
        node = data['nodes'][node_id]
        print(f"  {node['name']}: {'; '.join(node['pages']) or 'no page'}")


def cmd_lint(data):
    findings = []
    live_titles = {p['base_title'] for p in data['pages'] if not p['superseded']}
    all_titles = {p['base_title'] for p in data['pages']}
    for entry in data['index']:
        if entry['title'] not in all_titles:
            findings.append(('index-missing-from-mirror', entry['title'], 'not in the local copy'))
        elif entry['title'] not in live_titles:
            findings.append(('index-superseded', entry['title'], 'the only copy is superseded'))
        elif re.search('superseded', entry['title'], re.I):
            findings.append(('index-superseded', entry['title'], 'link text says superseded'))
    for e in data['edges']:
        for end in (e['from'], e['to']):
            if end not in data['nodes']:
                findings.append(('graph-broken-edge', e['graph'], f"{e['from']} -{e['relation']}-> {e['to']}: no node {end}"))
    for n in data['nodes'].values():
        if not n['pages']:
            findings.append(('graph-node-no-page', n['graph'], n['id']))
        for p in n['pages']:
            if p not in live_titles and p not in all_titles:
                findings.append(('graph-page-missing', n['graph'], f"{n['id']} -> {p}"))
    graphed = {re.sub(r'^Graph - ', '', p['base_title']) for p in data['pages']
               if p['base_title'].startswith('Graph - ') and not p['superseded']}
    for area in sorted({re.sub(r'^\d+\s+', '', e['area']) for e in data['index']}):
        if area not in graphed:
            findings.append(('area-without-graph', area, 'no Graph doc in the local copy'))
    copies = Counter(p['base_title'] for p in data['pages'] if not p['superseded'])
    for title in sorted(t for t, count in copies.items() if count > 1):
        findings.append(('duplicate-title', title, 'two live copies'))
    for node_id in data['duplicate_node_ids']:
        findings.append(('duplicate-node-id', node_id, 'appears in more than one table'))
    known = {n['name'].casefold() for n in data['nodes'].values()}
    known |= {a.casefold() for n in data['nodes'].values() for a in n['also_called']}
    for e in data['entities']:
        if e['name'].casefold() not in known:
            findings.append(('entity-without-node', e['doc'], e['name']))
    for p in data['pages']:
        if p['superseded']:
            continue
        for c in p['connections']:
            if c['name'].casefold() not in known and c['name'] not in all_titles:
                findings.append(('connection-unresolved', p['path'], f"{c['relation']} -> {c['name']}"))
    if not findings:
        print('lint: no findings')
    for check, item, detail in findings:
        print(f'{check:28} {item}  |  {detail}')
    print(f'{len(findings)} finding(s)')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='brindex', description=__doc__.split('\n')[0])
    parser.add_argument('--root', default=os.environ.get('SECOND_BRAIN_DIR', 'second-brain'),
                        help='folder of Markdown copies of the wiki (default: $SECOND_BRAIN_DIR or ./second-brain)')
    parser.add_argument('--out', default=None, help='where the index is written (default: ROOT/.brindex)')
    parser.add_argument('--rebuild', action='store_true', help='rebuild before answering')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('build', help='write the index')
    sub.add_parser('status', help='counts and build time')
    p = sub.add_parser('search', help='rank live pages by keyword')
    p.add_argument('terms', nargs='+')
    p.add_argument('--limit', type=int, default=10)
    p = sub.add_parser('lookup', help='find the node, pages and entity rows for a name')
    p.add_argument('name')
    p = sub.add_parser('neighbors', help='typed edges within N hops of a name or node id')
    p.add_argument('name')
    p.add_argument('--hops', type=int, default=2)
    sub.add_parser('lint', help='broken links, superseded and missing pages, unresolved names')
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        parser.error(f'not a folder: {root} (export the Second Brain .md files there or pass --root)')
    out_dir = Path(args.out) if args.out else root / OUT_NAME
    if args.command == 'build':
        data = build(root, out_dir)
        print(f"built {out_dir / 'index.json'}: {len(data['pages'])} pages, {len(data['nodes'])} nodes, "
              f"{len(data['edges'])} edges")
        return 0
    data = load(root, out_dir, args.rebuild)
    data['_out'] = str(out_dir)
    if args.command == 'status':
        cmd_status(data, out_dir)
    elif args.command == 'search':
        cmd_search(data, args.terms, args.limit)
    elif args.command == 'lookup':
        cmd_lookup(data, args.name)
    elif args.command == 'neighbors':
        cmd_neighbors(data, args.name, args.hops)
    elif args.command == 'lint':
        cmd_lint(data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
