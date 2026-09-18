"""Optional offline SigLIP-Base scoring and shot-bound sound effects."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys

AUDIO_EXT = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg'}
PROMPTS = {
    'flesh': [
        'A close-up photo of a fruit cut in half showing its inner flesh.',
        'A close-up photo of a bitten fruit with exposed flesh.',
        'A close-up photo of peeled fruit flesh.',
        'A close-up photo of sliced fruit showing the juicy interior.',
    ],
    'whole': ['A close-up photo of a whole uncut fruit with intact skin.',
              'A photo of whole fruits arranged on a table.',
              'A photo of hands holding whole unpeeled fruits.'],
    'packaging': ['A photo of whole fruits in a cardboard box.',
                  'A photo of fruit covered in white foam protective nets.'],
    'orchard': ['A photo of whole fruits hanging on trees.',
                'A photo of people harvesting fruits in an orchard.'],
    'person': ['A photo of a person displaying whole fruits.'],
    'other': ['A photo of an empty white plate.',
              'A photo of hands and packaging without exposed fruit flesh.'],
}


def model_directory():
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    return root / 'models' / 'siglip-base'


def audio_files(selected):
    if not str(selected).strip():
        raise ValueError('开启果肉音效后，请选择音效文件或文件夹')
    p = Path(selected).expanduser()
    files = [p] if p.is_file() else sorted(p.iterdir()) if p.is_dir() else []
    files = [f.resolve() for f in files if f.is_file() and f.suffix.lower() in AUDIO_EXT]
    if not files:
        raise ValueError('音效路径没有可用的 WAV、MP3、M4A、AAC、FLAC 或 OGG 文件')
    return files


def validate_settings(cfg):
    volume, gap = float(cfg.get('sfx_volume', .7)), float(cfg.get('sfx_gap', 2.5))
    if not math.isfinite(volume) or not 0 <= volume <= 2:
        raise ValueError('音效音量应在 0～200% 之间')
    if not math.isfinite(gap) or not 0 <= gap <= 60:
        raise ValueError('音效触发间隔应在 0～60 秒之间')
    return volume, gap


class FleshScorer:
    """Lazy CPU-only runtime; cache is keyed by media, view, time and model version."""
    def __init__(self, cache_path, model_dir=None):
        self.directory = Path(model_dir) if model_dir else model_directory()
        self.cache_path = Path(cache_path)
        self.session = None
        self.hits = self.misses = 0
        for filename in ('metadata.json', 'vision.onnx', 'text.npz'):
            if not (self.directory / filename).is_file():
                raise ValueError(f'果肉识别模型缺少 {filename}，请保留程序旁的 models 文件夹')
        self.version = hashlib.sha256((self.directory / 'metadata.json').read_bytes()).hexdigest()
        try:
            self.cache = json.loads(self.cache_path.read_text(encoding='utf-8'))
            if not isinstance(self.cache, dict): self.cache = {}
        except (OSError, ValueError):
            self.cache = {}

    def _load(self):
        if self.session is not None: return
        import numpy as np
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = min(8, os.cpu_count() or 4)
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(self.directory / 'vision.onnx'), sess_options=options,
                                           providers=['CPUExecutionProvider'])
        data = np.load(self.directory / 'text.npz', allow_pickle=False)
        self.text = data['embeddings']
        self.positive = data['positive'].astype(bool)

    def score(self, clip, start, length, width, height):
        from video_geometry import geometry_filter
        import numpy as np
        from PIL import Image
        path = Path(clip['path']); stat = path.stat()
        # Prefer the same clip midpoint across trims, but never inspect outside the used shot.
        midpoint = clip['dur'] / 2
        timestamp = midpoint if start <= midpoint < start + length else start + length / 2
        timestamp = min(timestamp, max(0, clip['dur'] - .02))
        view = geometry_filter(clip, width, height)
        key = hashlib.sha256(json.dumps([str(path.resolve()), stat.st_size, stat.st_mtime_ns,
                                        self.version, round(timestamp, 4), view], ensure_ascii=False).encode()).hexdigest()
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        self._load()
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{timestamp:.4f}', '-i', str(path),
                              '-frames:v', '1', '-vf', view + ',scale=480:-2',
                              '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True, check=True).stdout
        image = Image.open(io.BytesIO(raw)).convert('RGB').resize((224, 224), Image.Resampling.BICUBIC)
        pixels = ((np.asarray(image, dtype=np.float32) / 255 - .5) / .5).transpose(2, 0, 1)[None]
        feature = self.session.run(None, {'pixel_values': pixels})[0]
        feature /= np.linalg.norm(feature, axis=-1, keepdims=True)
        sims = (feature @ self.text.T)[0]
        margin = float(sims[self.positive].max() - sims[~self.positive].max())
        result = dict(match=margin >= 0, margin=margin, sample_time=timestamp)
        self.cache[key] = result
        self.misses += 1
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.cache_path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.cache, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.cache_path)
        return result


def shot_windows(shots, speed, fps):
    """Use the same explicit per-shot frame counts as FFmpeg's video concatenation."""
    position = 0
    for i, shot in enumerate(shots):
        frames = shot.get('frames', max(1, math.ceil(shot['len'] * fps - 1e-8)))
        length = frames / fps / speed
        yield i, position, length
        position += length


def plan_events(shots, speed, fps, scorer, sounds, cfg):
    _, gap = validate_settings(cfg)
    events, inspected = [], []
    next_time = 0.0
    for i, position, length in shot_windows(shots, speed, fps):
        shot = shots[i]
        result = scorer.score(shot['clip'], shot['start'], shot['len'], cfg['width'], cfg['height'])
        inspected.append(dict(shot=i, **result))
        if (i + 1) % 10 == 0:
            print(f'  果肉识别 {i+1}/{len(shots)} 镜', flush=True)
        if not result['match'] or position + 1e-6 < next_time: continue
        sound = random.choice(sounds)
        duration = min(length, sound['duration'])
        events.append(dict(shot=i, start=position, duration=duration, path=str(sound['path']),
                           sample_time=result['sample_time'], margin=result['margin']))
        next_time = max(position + gap, position + duration)
    return events, inspected


def add_audio_filters(inputs, filters, events, first_index, bgm_label, duration, volume):
    labels = [bgm_label]
    for n, event in enumerate(events):
        inputs.extend(['-i', event['path']])
        length = event['duration']; fade = min(.04, length / 4)
        # Sample-based delay avoids millisecond rounding moving a sound into the next shot.
        delay = round(event['start'] * 48000)
        filters.append(f'[{first_index+n}:a]aresample=48000,atrim=0:{length:.6f},asetpts=PTS-STARTPTS,'
                       f'aformat=sample_fmts=fltp:channel_layouts=stereo,volume={volume},'
                       f'afade=t=in:st=0:d={fade:.6f},afade=t=out:st={length-fade:.6f}:d={fade:.6f},'
                       f'adelay={delay}S:all=1[sfx{n}]')
        labels.append(f'[sfx{n}]')
    filters.append(''.join(labels) + f'amix=inputs={len(labels)}:duration=first:normalize=0,'
                   f'alimiter=limit=0.95:level=0:latency=1,atrim=0:{duration:.6f}[aout]')
