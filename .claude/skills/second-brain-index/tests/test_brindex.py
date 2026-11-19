"""Tests for brindex.py on a small fixture shaped like the Second Brain (no Drive access)."""
import contextlib
import io
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import brindex  # noqa: E402

FILES = {
    '00 Control/Index.md': """\
        # Index

        Read this first. [Handovers folder](https://example.com/handovers)

        ## [AISI](https://example.com/aisi)

        - [Graph - AISI](https://example.com/g) (v7)
        - [Entities - AISI](https://example.com/e)
        - [Hub - AISI](https://example.com/h)
        - [Missing Page](https://example.com/m)
        - [Old Hub](https://example.com/old)

        ## Landlord

        - [Hub - Landlord](https://example.com/hl)
        """,
    '00 Control/Graph - AISI.md': """\
        # Graph - AISI

        **Version 2026-10-24 v7 (replaces v6).**

        ## Nodes

        | ID | Name | Kind | Also called | Page (open this) |
        | :-- | :-- | :-- | :-- | :-- |
        | prog.toyota-817d | Toyota 817D | Program | Toyota 311D | Project - Toyota 817D |
        | cust.htna | HTNA | Customer | Hayashi | Customer - HTNA |
        | per.dai-tran | Dai Tran | Quality Engineer | none | Hub - AISI |

        ## Edges

        | # | From | Relation | To | Note | Source | Conf. |
        | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
        | 1 | prog.toyota-817d | customer | cust.htna | AISI ships to HTNA | Entities | 0.95 |
        | 2 | prog.toyota-817d | possible standard | std.sqam | | Entities | 0.70 check |
        | 3 | cust.htna | customer | cust.missing | | Entities | 0.90 |
        """,
    '02 AISI/Project - Toyota 817D.md': """\
        # Project - Toyota 817D / 311D

        Version 2026-10-20 v3. The Toyota 817D rear wheel liner program ships to HTNA.

        ## Connections

        - customer -> HTNA
        - see also -> Hub - AISI
        """,
    '02 AISI/Hub - AISI.md': "# Hub - AISI\n\nThe AISI hub.\n",
    '02 AISI/Customer - HTNA.md': "# Customer - HTNA\n\nHTNA ships Toyota parts.\n",
    '02 AISI/Entities - AISI.md': """\
        | Name | Kind | Also called | Pages |
        | :-- | :-- | :-- | :-- |
        | Toyota 817D | Program | Toyota 311D | Project |
        | Welding Shop | Place | none | Hub |
        """,
    '99 Superseded/Old Hub.md': "# Old Hub\n",
}


def build_fixture(root):
    for name, body in FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding='utf-8')


def run(root, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        brindex.main(['--root', str(root), *args])
    return out.getvalue()


class BrIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        build_fixture(self.root)
        self.data = brindex.build(self.root, self.root / '.brindex')

    def tearDown(self):
        self.tmp.cleanup()

    def test_builds_nodes_edges_and_index_entries(self):
        self.assertEqual(set(self.data['nodes']), {'prog.toyota-817d', 'cust.htna', 'per.dai-tran'})
        self.assertEqual(len(self.data['edges']), 3)
        self.assertEqual(len(self.data['index']), 6)
        self.assertTrue(any(e['possible'] for e in self.data['edges']))

    def test_superseded_pages_are_flagged_and_excluded_from_lookup(self):
        old = next(p for p in self.data['pages'] if p['base_title'] == 'Old Hub')
        self.assertTrue(old['superseded'])
        self.assertIsNone(brindex.page_by_title(self.data, 'Old Hub'))

    def test_lookup_matches_name_and_also_called(self):
        out = run(self.root, 'lookup', 'toyota 311d')
        self.assertIn('prog.toyota-817d  Toyota 817D  [Program]', out)
        self.assertIn('page: Project - Toyota 817D', out)

    def test_neighbors_follow_valid_edges_only(self):
        out = run(self.root, 'neighbors', 'Toyota 817D', '--hops', '1')
        self.assertIn('prog.toyota-817d -customer-> cust.htna', out)
        self.assertNotIn('possible', out)  # its target std.sqam has no node, so the edge is not walked
        self.assertNotIn('std.sqam', out)
        self.assertNotIn('cust.missing', out)

    def test_neighbors_two_hops_reach_the_second_node(self):
        out = run(self.root, 'neighbors', 'prog.toyota-817d', '--hops', '2')
        self.assertIn('HTNA: Customer - HTNA', out)

    def test_search_ranks_the_title_match_and_skips_superseded(self):
        out = run(self.root, 'search', 'toyota')
        first = out.splitlines()[0]
        self.assertIn('02 AISI/Project - Toyota 817D.md', first)
        self.assertNotIn('Old Hub', out)

    def test_lint_reports_each_broken_thing(self):
        out = run(self.root, 'lint')
        for check in ('index-missing-from-mirror', 'index-superseded', 'graph-broken-edge',
                      'area-without-graph', 'entity-without-node'):
            self.assertIn(check, out)
        self.assertIn('Missing Page', out)
        self.assertIn('Welding Shop', out)
        self.assertIn('Landlord', out)
        self.assertEqual(out.count('graph-broken-edge'), 2)

    def test_status_counts_and_out_folder_is_self_ignoring(self):
        out = run(self.root, 'status')
        self.assertIn('nodes: 3; edges: 3', out)
        self.assertEqual((self.root / '.brindex' / '.gitignore').read_text(), '*\n')

    def test_stale_index_rebuilds_on_next_query(self):
        index = self.root / '.brindex' / 'index.json'
        before = index.stat().st_mtime
        target = self.root / '02 AISI' / 'Hub - AISI.md'
        target.write_text('# Hub - AISI\n\nnewer\n', encoding='utf-8')
        future = before + 10
        import os
        os.utime(target, (future, future))
        run(self.root, 'status')
        self.assertGreater(index.stat().st_mtime, before)


if __name__ == '__main__':
    unittest.main()
