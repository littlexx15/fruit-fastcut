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
            self.assertAlmostEqual(sum(s['len'] for s in shots), 36, places=3)
            self.assertTrue(any(s['clip'] in self.pool[:70] for s in shots[1:]))
            self.assertTrue(all(s['start'] + s['len'] <= s['clip']['dur'] for s in shots))
            for shot in shots:
                self.assertEqual(usage[shot['key']], min(usage[str(Path(c['path']).resolve())] for c in self.pool))
                usage[shot['key']] += 1
        self.assertEqual(len(usage), 100)
        self.assertLessEqual(max(usage.values()) - min(usage.values()), 2)

    def test_small_pool_recycles_only_after_round(self):
        shots = b.plan_shots(self.pool[:1], [], b.CONFIG, 3)
        self.assertGreater(len(shots), 1)
        self.assertAlmostEqual(sum(s['len'] for s in shots), 3)

    def test_hooks_can_supply_body_without_clips(self):
        self.assertTrue(b.plan_shots(self.pool, [], b.CONFIG, 36))

    def test_unified_pool_needs_no_hooks(self):
        shots = b.plan_shots([], self.pool, b.CONFIG, 36)
        self.assertTrue(shots)
        self.assertLessEqual(shots[0]['len'], max(b.CONFIG['shot_sec']))

    def test_legacy_hook_label_does_not_reserve_first_shot(self):
        usage = Counter({str(Path(self.pool[0]['path']).resolve()): 100})
        shots = b.plan_shots(self.pool[:1], self.pool[1:], b.CONFIG, 3, usage)
        self.assertNotEqual(shots[0]['clip'], self.pool[0])

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
