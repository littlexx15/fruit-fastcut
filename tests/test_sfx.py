import tempfile
from pathlib import Path
import unittest
from flesh_sfx import audio_files, plan_events, validate_settings


class Scorer:
    def score(self, clip, start, length, width, height):
        return dict(match=clip['positive'], sample_time=start + length / 2, margin=.01)


class SfxTests(unittest.TestCase):
    def test_speed_gap_and_shot_end(self):
        shots = [dict(clip=dict(positive=v), start=0, len=1, frames=30)
                 for v in (True, False, True, True, True)]
        cfg = dict(width=1080, height=1920, sfx_gap=1.5, sfx_volume=.7)
        events, results = plan_events(shots, 2, 30, Scorer(),
                                      [dict(path='eat.wav', duration=5)], cfg)
        self.assertEqual([e['shot'] for e in events], [0, 3])
        self.assertEqual([e['start'] for e in events], [0, 1.5])
        self.assertTrue(all(e['duration'] == .5 for e in events))
        self.assertFalse(results[1]['match'])

    def test_short_sound_never_loops(self):
        events, _ = plan_events([dict(clip=dict(positive=True), start=0, len=1)], 1, 30,
            Scorer(), [dict(path='short.wav', duration=.15)], dict(width=10,height=10))
        self.assertEqual(events[0]['duration'], .15)

    def test_paths_and_validation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td); (p/'a.wav').touch();(p/'ignore.txt').touch()
            self.assertEqual(audio_files(p), [(p/'a.wav').resolve()])
            self.assertEqual(audio_files(p/'a.wav'), [(p/'a.wav').resolve()])
            with self.assertRaises(ValueError):audio_files('')
        for cfg in (dict(sfx_gap=-1),dict(sfx_volume=float('nan')),dict(sfx_volume=3)):
            with self.assertRaises(ValueError):validate_settings(cfg)

if __name__=='__main__':unittest.main()
