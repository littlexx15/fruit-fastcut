from pathlib import Path
import unittest
import batch_cut as b


class MusicTests(unittest.TestCase):
    def test_random_rounds_use_each_song_and_no_adjacent_repeat(self):
        songs = ['a.mp3', 'b.wav', 'c.m4a']
        for _ in range(50):
            plan = b.plan_music(songs + songs, 30)
            self.assertEqual(len(plan), 30)
            for i in range(0, 30, 3):
                self.assertEqual(set(plan[i:i + 3]), set(songs))
            self.assertTrue(all(a != c for a, c in zip(plan, plan[1:])))

    def test_single_song_and_empty_folder(self):
        self.assertEqual(b.plan_music(['a.wav'], 3), ['a.wav'] * 3)
        with self.assertRaises(ValueError):
            b.plan_music([], 1)

    def test_music_folder_selection(self):
        base = Path.cwd() / 'pool'
        external = Path.cwd() / 'external music'
        self.assertEqual(b.resolve_bgm_directory(base), base / 'bgm')
        self.assertEqual(b.resolve_bgm_directory(base, str(external)), external)
        self.assertEqual(b.resolve_bgm_directory(base, 'music'), base / 'music')
