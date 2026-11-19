---
name: second-brain-index
description: Build and query a local GraphRAG-style index of the Second Brain (the Google Drive wiki) from its Markdown copies, so Claude finds the right page, follows typed links between people, programs, customers and standards, and lints the wiki for broken links, superseded pages and missing graph docs. Use before answering a question that names a person, program, customer, supplier or standard, when looking for the page that covers a topic, and when checking the wiki after a weekly ingest. Skip for code questions and for pages that are not in the local copy.
---

# Second Brain index

A small index built by `scripts/brindex.py` (Python 3, standard library only). It is the Claude Code counterpart of the GraphRAG method the Second Brain uses itself: the `Index` says which page to read, each `Graph - <Area>` doc says how things connect, and this script reads both so the lookup is a command instead of a manual scan. It is a keyword index, not an embedding index, and it does not change anything in the Second Brain.

## Setup

The wiki lives in Google Drive. The index reads a **local folder of its Markdown copies**: the `.md` files are the master copies, the Google Docs are backups (see the Index maintenance rule). Export or sync those files to a folder, then:

```
export SECOND_BRAIN_DIR=/path/to/second-brain   # or pass --root DIR
B="python3 .claude/skills/second-brain-index/scripts/brindex.py"
$B status
```

The index is written to `ROOT/.brindex/index.json` (self-ignoring, never commit it). Every query rebuilds it first when a `.md` file is newer than the index; `--rebuild` forces it.

## Commands

| Question | Command |
|---|---|
| Which page covers a topic? | `$B search "wheel liner" --limit 5` |
| Who or what is this name, and which page opens it? | `$B lookup "Toyota 311D"` (matches Name and Also called) |
| What does this connect to, two hops out? | `$B neighbors prog.toyota-817d --hops 2` |
| What is broken in the wiki? | `$B lint` |
| Are the counts what I expect? | `$B status` |

Use `lookup` first for any name, then `neighbors` for its links, then open only the pages it names. This matches the Index's own lookup rule: read at most three pages directly.

## How to read the output

- `neighbors` prints each edge as `from -relation-> to conf N`. An edge marked `(possible)` is a hint, not a fact. `check` means confidence below 0.85. Only edges whose two ends are both nodes are walked, so a dangling edge never shows up as a neighbour.
- `search` ranks live pages only. A title match outranks body matches. Superseded copies are excluded.
- `lint` reports one finding per line: `check  item  |  detail`. Checks:
  - `index-missing-from-mirror`: an Index entry with no `.md` in the local copy (export it, or it is a Google Doc only).
  - `index-superseded`: an Index entry whose only copy is superseded.
  - `graph-broken-edge`: an edge that names a node ID that is not in any node table.
  - `graph-node-no-page`, `graph-page-missing`: a node with no page, or a page title not found.
  - `area-without-graph`: an Index area with no `Graph - <Area>` doc. Trading and Investments is expected to show here until its graph exists.
  - `duplicate-title`: two live copies of one title (often a Google Doc backup exported next to its `.md`).
  - `duplicate-node-id`: one node ID in two graphs.
  - `entity-without-node`: an Entities row with no matching node. Often correct (places and documents need no node); the graph rules decide.
  - `connection-unresolved`: a Connections line whose name is neither a page nor a node.

## Limits (state these when they matter)

- Keyword matching only: a synonym or a misspelt name finds nothing. Try `lookup` with the alias, then ask.
- It reads what is in the local folder. A page that exists only in Drive is invisible until exported.
- Edges come from the Graph docs. The index does not infer links; a missing edge means the doc does not state it.
- The table parser expects the column names the Graph docs use (`ID`, `Name`, `Also called`, `Page`, `From`, `Relation`, `To`, `Conf.`). A doc with other headers is skipped, and `status` shows the counts so a silent skip is visible.
- Name matching is case-insensitive and exact. Two people with the same name are two nodes only if the graph gives them two IDs.

## Rules

- The index guides the answer; the page is the source. Cite the page title (and its Drive link from the Index) for any fact.
- Never write index output into the Second Brain or into a page.
- Do not treat a `(possible)` edge or a `check` edge as settled; say so in the answer.
- Superseded pages are never a source for a current fact.

## Tests

```
python3 .claude/skills/second-brain-index/tests/test_brindex.py
```

The tests build a small fixture shaped like the Second Brain (no Drive access) and check build, lookup, neighbours, search ranking, superseded handling, lint and the stale-index rebuild.
