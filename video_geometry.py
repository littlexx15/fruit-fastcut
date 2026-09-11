"""Display orientation and conservative, persistent black-border detection."""
import json
import math
from pathlib import Path
import subprocess


def probe_media(path):
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_streams',
        '-show_format', '-of', 'json', str(path)], capture_output=True,
        text=True, encoding='utf-8', errors='replace', check=True)
    data = json.loads(result.stdout)
    stream = data['streams'][0]
    width, height = int(stream['width']), int(stream['height'])
    rotation = float(stream.get('tags', {}).get('rotate', 0))
    for side in stream.get('side_data_list', []):
        if 'rotation' in side:
            rotation = float(side['rotation'])
    try:
        a, b = map(float, stream.get('sample_aspect_ratio', '1:1').split(':'))
        sar = a / b if a > 0 and b > 0 else 1
    except (ValueError, ZeroDivisionError):
        sar = 1
    display_width, display_height = width * sar, height
    # FFmpeg autorotation happens before our filter graph.
    if round(rotation / 90) % 2:
        width, height = height, width
        display_width, display_height = display_height, display_width
    return dict(width=width, height=height,
                display_width=display_width, display_height=display_height,
                duration=float(data['format']['duration']))


def _edge_runs(raw, width, height):
    black = [max(raw[i:i + 3]) <= 12 for i in range(0, len(raw), 3)]
    rows = [sum(black[y * width:(y + 1) * width]) >= width * .995 for y in range(height)]
    cols = [sum(black[x::width]) >= height * .995 for x in range(width)]

    def run(values):
        return next((i for i, value in enumerate(values) if not value), len(values))
    return run(cols), run(rows), run(cols[::-1]), run(rows[::-1])


def detect_black_borders(path, info):
    """Only remove edge strips that are almost entirely black at all 3 sample times."""
    width, height = info['width'], info['height']
    scale = min(1, 256 / max(width, height))
    sw, sh = max(2, round(width * scale)), max(2, round(height * scale))
    samples = []
    for fraction in (.1, .5, .85):
        time = max(0, min(info['duration'] * fraction, info['duration'] - .05))
        result = subprocess.run([
            'ffmpeg', '-v', 'error', '-ss', str(time), '-i', str(path),
            '-frames:v', '1', '-vf', f'scale={sw}:{sh}', '-pix_fmt', 'rgb24',
            '-f', 'rawvideo', '-'], capture_output=True, check=True)
        if len(result.stdout) != sw * sh * 3:
            return None
        samples.append(_edge_runs(result.stdout, sw, sh))
    strips = [min(row[i] for row in samples) for i in range(4)]
    # A completely black/dark sample is not evidence for trimming a border.
    if any(row[0] + row[2] >= sw * .9 or row[1] + row[3] >= sh * .9 for row in samples):
        return None
    edges = []
    for i, value in enumerate(strips):
        # Two small-frame pixels and temporal stability protect dark product scenes.
        stable = max(row[i] for row in samples) - value <= 2
        axis, small_axis = (width, sw) if i % 2 == 0 else (height, sh)
        edges.append(math.ceil((value + 1) * axis / small_axis / 2) * 2
                     if value >= 2 and stable else 0)
    left, top, right, bottom = edges
    if not any(edges):
        return None
    cw, ch = (width - left - right) // 2 * 2, (height - top - bottom) // 2 * 2
    if cw < width * .15 or ch < height * .15:
        return None
    return [left, top, cw, ch]


def inspect_geometry(path, cache):
    path = Path(path)
    stat = path.stat()
    key = str(path.resolve())
    signature = [stat.st_size, stat.st_mtime_ns, 1]
    saved = cache.get(key)
    if saved and saved.get('signature') == signature:
        return saved['info']
    info = probe_media(path)
    info['border_crop'] = detect_black_borders(path, info)
    cache[key] = dict(signature=signature, info=info)
    return info


def geometry_filter(clip, width, height):
    """Rotate mismatched orientations, scale uniformly to cover, crop overflow."""
    info = clip.get('geometry') or probe_media(clip['path'])
    crop = info.get('border_crop')
    filters = []
    if crop:
        x, y, cw, ch = crop
        filters.append(f'crop={cw}:{ch}:{x}:{y}')
        cw *= info['display_width'] / info['width']
        ch *= info['display_height'] / info['height']
    else:
        cw, ch = info['display_width'], info['display_height']
    # A face crop can change width/height classification; preserve the original orientation.
    if clip.get('face_cropped') and clip.get('source_size'):
        cw, ch = clip['source_size']
    rotate = (cw > ch and width < height) or (cw < ch and width > height)
    # Honor non-square source pixels before calculating the cover transform.
    filters.extend(['scale=iw*sar:ih', 'setsar=1'])
    if rotate:
        filters.append('transpose=clock')
    filters.extend([f'scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2',
                    f'crop={width}:{height}', 'setsar=1'])
    return ','.join(filters)
