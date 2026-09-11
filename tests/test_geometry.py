import subprocess
import tempfile
from pathlib import Path
import unittest

from video_geometry import probe_media, detect_black_borders, geometry_filter


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def make_clip(self, name, width, height, extra=''):
        path = self.root / (name + '.mp4')
        filters = f'drawbox=x=0:y=0:w=iw/4:h=ih/4:color=red:t=fill'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        f'color=yellow:s={width}x{height}:r=10:d=1', '-vf', filters + extra,
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', str(path)], check=True)
        info = probe_media(path)
        info['border_crop'] = detect_black_borders(path, info)
        return dict(path=str(path), geometry=info)

    def render(self, clip, width, height):
        vf = geometry_filter(clip, width, height)
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', clip['path'],
                                      '-vf', vf, '-frames:v', '1', '-pix_fmt', 'rgb24',
                                      '-f', 'rawvideo', '-'])
        self.assertEqual(len(raw), width * height * 3)
        # All four full edges must contain image content, not padding.
        pixels = [raw[i:i+3] for i in range(0, len(raw), 3)]
        for edge in (pixels[:width], pixels[-width:], pixels[::width], pixels[width-1::width]):
            self.assertGreater(sum(max(p) for p in edge) / len(edge), 100)
        return vf, pixels

    def test_all_input_and_output_orientations(self):
        for width, height in [(320, 180), (180, 320), (320, 240), (240, 320), (240, 240)]:
            clip = self.make_clip(f'{width}x{height}', width, height)
            self.assertIsNone(clip['geometry']['border_crop'])
            for ow, oh in [(320, 180), (180, 320)]:
                with self.subTest(source=(width, height), output=(ow, oh)):
                    vf, pixels = self.render(clip, ow, oh)
                    rotate = (width > height and ow < oh) or (width < height and ow > oh)
                    self.assertEqual('transpose=clock' in vf, rotate)
                    x = int(ow * (.99 if rotate else .01))
                    pixel = pixels[int(oh * .01) * ow + x]
                    self.assertGreater(pixel[0], 150)
                    self.assertLess(pixel[1], 100)
                    self.assertIn('force_original_aspect_ratio=increase', vf)

    def test_square_subject_keeps_its_shape(self):
        for width, height in [(320, 180), (180, 320), (320, 240), (240, 320), (240, 240)]:
            clip = self.make_clip(f'square-subject-{width}x{height}', width, height,
                                 ',drawbox=x=(iw-50)/2:y=(ih-50)/2:w=50:h=50:color=blue:t=fill')
            for ow, oh in [(320, 180), (180, 320)]:
                with self.subTest(source=(width, height), output=(ow, oh)):
                    _, pixels = self.render(clip, ow, oh)
                    points = [(i % ow, i // ow) for i, p in enumerate(pixels)
                              if p[2] > 150 and p[0] < 100 and p[1] < 100]
                    self.assertTrue(points)
                    xs, ys = zip(*points)
                    self.assertLessEqual(abs((max(xs) - min(xs)) - (max(ys) - min(ys))), 2)

    def test_existing_black_borders_are_removed(self):
        for name, w, h, pad in [('letterbox', 320, 180, ',pad=320:240:0:30:black'),
                                ('pillarbox', 180, 320, ',pad=320:320:70:0:black')]:
            clip = self.make_clip(name, w, h, pad)
            self.assertIsNotNone(clip['geometry']['border_crop'])
            for ow, oh in [(320, 180), (180, 320)]:
                self.render(clip, ow, oh)

    def test_rotation_metadata_is_applied_only_once(self):
        original = self.make_clip('unrotated', 320, 180)
        target = self.root / 'metadata.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-display_rotation', '90',
                        '-i', original['path'], '-c', 'copy', '-y', str(target)], check=True)
        info = probe_media(target)
        self.assertEqual((info['width'], info['height']), (180, 320))
        clip = dict(path=str(target), geometry=info)
        vf, _ = self.render(clip, 180, 320)
        self.assertNotIn('transpose', vf)

    def test_face_crop_keeps_original_orientation(self):
        clip = dict(face_cropped=True, source_size=[180, 320],
                    geometry=dict(width=180, height=100, display_width=180, display_height=100))
        self.assertNotIn('transpose', geometry_filter(clip, 180, 320))
        self.assertIn('transpose', geometry_filter(clip, 320, 180))

    def test_black_scene_is_not_treated_as_border(self):
        path = self.root / 'dark.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=black:s=320x180:r=10:d=1', '-y', str(path)], check=True)
        self.assertIsNone(detect_black_borders(path, probe_media(path)))


if __name__ == '__main__':
    unittest.main()
