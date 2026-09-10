import ast
from collections import Counter
from pathlib import Path
import random
import unittest

import batch_cut as b


class PlanningTests(unittest.TestCase):
    def setUp(self):
        random.seed(42)
        self.pool = [dict(path=f'source{i % 10}_clip{i}.mp4', source=f'source{i % 10}',
                          dur=1.1, face_cropped=False) for i in range(100)]

    def test_batch_uses_all_material_without_local_repeats(self):
        usage = Counter()
        for _ in range(20):
            shots = b.plan_shots(self.pool[:70], self.pool[70:], b.CONFIG, 36, usage)
            self.assertEqual(len(shots), len({s['key'] for s in shots}))
            sources = [s['clip']['source'] for s in shots]
            for i, source in enumerate(sources):
                self.assertNotIn(source, sources[max(0, i - 2):i])
            self.assertAlmostEqual(sum(s['len'] for s in shots), 36, places=3)
            self.assertTrue(any(s['clip'] in self.pool[:70] for s in shots[1:]))
            self.assertTrue(all(s['start'] + s['len'] <= s['clip']['dur'] for s in shots))
            usage.update(s['key'] for s in shots)
        self.assertEqual(len(usage), 100)
        self.assertLessEqual(max(usage.values()) - min(usage.values()), 2)

    def test_small_pool_fails_without_recycling(self):
        with self.assertRaises(ValueError):
            b.plan_shots(self.pool[:1], [], b.CONFIG, 36)

    def test_hooks_can_supply_body_without_clips(self):
        self.assertTrue(b.plan_shots(self.pool, [], b.CONFIG, 36))

    def test_face_confirmation_is_local_and_requires_peers(self):
        source = Path(b.__file__).with_name('prep_clips.py')
        tree = ast.parse(source.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'confirm']
        scope = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
        confirm = scope['confirm']
        self.assertEqual(confirm([(0, 200)], 1920, 2, .1), [])
        self.assertEqual(confirm([(0, 200), (5, 200)], 1920, 2, .1), [])
        self.assertEqual(len(confirm([(0, 200), (.2, 210)], 1920, 2, .1)), 2)


if __name__ == '__main__':
    unittest.main()
