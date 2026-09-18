"""Blank-line separated, unique caption groups; no implicit reuse."""
import random


def parse_captions(text):
    groups, current = [], []
    for line in str(text).splitlines() + ['']:
        line = line.strip()
        if line:
            current.append(line)
        elif current:
            if len(current) > 3:
                raise ValueError(f'第 {len(groups)+1} 组超过3行；每组最多3行，组间请空一行')
            groups.append(current)
            current = []
    unique, seen = [], set()
    for group in groups:
        key = tuple(group)
        if key not in seen:
            unique.append(group)
            seen.add(key)
    return unique


def plan_captions(cfg, count):
    if not cfg.get('batch_caption_enabled', False):
        return [list(cfg['caption']) for _ in range(count)]
    groups = parse_captions(cfg.get('batch_caption_text', ''))
    if len(groups) < count:
        raise ValueError(f'去重后有 {len(groups)} 组文案，但要生成 {count} 条视频。请补充文案或减少生成条数。')
    if cfg.get('batch_caption_shuffle', False):
        random.shuffle(groups)
    return groups[:count]
