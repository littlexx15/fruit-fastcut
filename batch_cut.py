#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_cut.py —— 短视频批量混剪生产脚本

用法:
    python3 batch_cut.py --n 20

目录约定(和脚本同级):
    hooks/   钩子素材 —— 掰开/切开的剖面特写。每条片的第0帧只从这里抽。
    clips/   常规素材池 —— 其余所有镜头。建议 60-150 个。
    bgm/     背景音乐,放几首,随机选。
    out/     成片输出(自动创建)

参数在下面 CONFIG 里改。
"""

import argparse, functools, json, os, random, subprocess, sys, tempfile
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
print = functools.partial(print, flush=True)

# ============================ CONFIG ============================
CONFIG = {
    # --- 成片规格 ---
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "total_sec": (35, 40),      # 成片总时长随机区间

    # --- 节奏(实测爆款参数) ---
    "hook_sec": 1.4,            # 首个钩子镜头时长,略长于其余
    "shot_sec": (0.7, 0.9),    # 其余每镜时长随机区间
    "source_gap": 2,           # 同一原片的两次出场之间至少隔两个镜头

    # --- 屏幕文案:三行,固定不动,左上角 ---
    "caption": [
        "都去吃这个红心蜜柚🍊",
        "就喜欢这种爆汁的清甜感",
        "越吃越上头巨好吃🥰",
    ],
    "font_size": 36,
    "font_color": "white",
    "font_border": 2,
    "cap_x": 32,
    "cap_y": 80,
    "line_spacing": 10,

    # --- 音频 ---
    "bgm_volume": 1.0,
    "bgm_fadeout": 1.5,

    # --- 去重扰动(降低同质化判定风险) ---
    "jitter": {
        "mirror_prob": 0.0,
        "zoom_range": (1.00, 1.00),  # 兼容旧配置；出片不再随机放大
        "speed_range": (0.97, 1.03), # 整片随机变速
        "color_shift": True,      # 轻微色温/饱和度扰动
    },

    # --- 编码 ---
    "crf": 23,
    "preset": "veryfast",
}
# ================================================================

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".flac"}


def find_font():
    """按平台找一个能显示中文的字体。"""
    c = []
    if os.name == "nt":
        wd = os.environ.get("WINDIR", r"C:\Windows")
        c += [os.path.join(wd, "Fonts", f) for f in
              ("msyhbd.ttc", "msyh.ttc", "simhei.ttf",
               "msyh.ttf", "simsun.ttc", "arialuni.ttf")]
    elif sys.platform == "darwin":
        c += ["/System/Library/Fonts/PingFang.ttc",
              "/System/Library/Fonts/STHeiti Medium.ttc",
              "/System/Library/Fonts/Hiragino Sans GB.ttc"]
    c += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
          "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
          "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
    for f in c:
        if os.path.isfile(f):
            return f
    return None


def ff_path(p):
    """把路径转成 ffmpeg 滤镜里安全的写法(反斜杠和冒号必须处理)。"""
    return str(p).replace("\\", "/").replace(":", "\\:")


FONT = find_font()


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError(f"命令失败:\n{' '.join(cmd[:12])}...\n{r.stderr[-1500:]}")
    return r.stdout


def duration(path):
    """读取媒体时长(秒)。"""
    try:
        out = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=nw=1:nk=1", str(path)])
        return float(out.strip())
    except Exception:
        return 0.0


def scan(folder, exts):
    p = Path(folder)
    if not p.is_dir():
        return []
    return sorted([f for f in p.iterdir() if f.suffix.lower() in exts])


def build_clip_index(files, min_dur):
    """预扫时长,过滤掉太短的素材。只做一次,结果缓存。"""
    idx, dropped = [], 0
    crop_info = {}
    if files:
        report = Path(files[0]).parent.parent / 'prep_report.json'
        if report.exists():
            entries = json.loads(report.read_text(encoding='utf-8'))
            crop_info = {s['file']: dict(face_cropped=s.get('crop_y', 0) > 0,
                                       source=entry['file'], source_start=s['start'])
                         for entry in entries for s in entry.get('segments', [])}
    for f in files:
        d = duration(f)
        if d >= min_dur:
            idx.append({"path": str(f), "dur": d,
                        **crop_info.get(f.name, dict(face_cropped=False,
                            source=f.stem.rsplit('_', 1)[0], source_start=0))})
        else:
            dropped += 1
    if dropped:
        print(f"  跳过 {dropped} 个短于 {min_dur:.2f}s 的素材")
    return idx


def pick_segment(clip, seg_len):
    """
    在一条素材里随机取一段。返回 (起点, 实际长度)。
    素材比请求的短时,按素材实际长度取,不会拼出空帧。
    """
    L = min(seg_len, clip["dur"] - 0.02)
    max_start = max(0.0, clip["dur"] - L - 0.05)
    start = random.uniform(0.0, max_start) if max_start > 0.01 else 0.0
    return start, L


def write_caption_file(tmpdir, lines):
    p = Path(tmpdir) / "cap.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def plan_shots(hooks, clips, cfg, total, usage=None):
    """整批按使用次数选材；一条内切片唯一，同源之间留间隔。"""
    usage = usage if usage is not None else Counter()
    pool = {str(Path(c['path']).resolve()): c for c in hooks + clips}
    hook_keys = {str(Path(c['path']).resolve()) for c in hooks}
    used, sources, shots = set(), [], []
    source_counts = Counter()
    remaining = total
    gap = max(0, int(cfg.get('source_gap', 2)))
    while remaining > 0.001:
        recent = set(sources[-gap:]) if gap else set()
        choices = [(key, c) for key, c in pool.items()
                   if key not in used and (shots or key in hook_keys)
                   and c.get('source', key) not in recent and c['dur'] > .02]
        if not choices:
            raise ValueError(f'不重复选镜且同源间隔{gap}镜时，素材不足以完成{total:.1f}秒。'
                             '请缩短成片或补充不同原片；不会循环复用切片。')
        random.shuffle(choices)
        key, c = min(choices, key=lambda item: (
            usage[item[0]], source_counts[item[1].get('source', item[0])]))
        wanted = cfg['hook_sec'] if not shots else random.uniform(*cfg['shot_sec'])
        length = min(wanted, c['dur'] - .02, remaining)
        if 0 < remaining - length < .3:
            if c['dur'] - .02 >= remaining:
                length = remaining
            else:
                length = min(length, remaining - .3)
        start, length = pick_segment(c, length)
        shots.append(dict(clip=c, start=start, len=length, key=key))
        used.add(key)
        source = c.get('source', key)
        sources.append(source)
        source_counts[source] += 1
        remaining -= length
    return shots


def build_variant(vid, hooks, clips, bgms, cfg, outdir, tmpdir, usage=None):
    W, H, FPS = cfg["width"], cfg["height"], cfg["fps"]
    jit = cfg["jitter"]

    total = random.uniform(*cfg["total_sec"])

    # 时长按实际截取长度累计，并提前计入最终播放速度。
    spd = random.uniform(*jit['speed_range'])
    if abs(spd - 1.0) <= .005:
        spd = 1.0
    shots = plan_shots(hooks, clips, cfg, total * spd, usage)
    hook = shots[0]['clip']

    # ---- 2. 拼 filter_complex ----
    inputs, filters, labels = [], [], []
    real_total = 0.0
    for n, s in enumerate(shots):
        c = s["clip"]
        st, L = s['start'], s['len']
        real_total += L
        inputs += ["-ss", f"{st:.3f}", "-t", f"{L:.3f}", "-i", c["path"]]

        # 正常竖屏产品素材不会被裁；人脸裁切改变比例后等比铺满。
        rotate = "transpose=clock," if W > H else ""
        fit = (f"scale={W}:{H}:force_original_aspect_ratio=increase:"
               f"force_divisible_by=2,crop={W}:{H}" if c.get('face_cropped', False)
               else f"scale={W}:{H}")
        f = (f"[{n}:v]{rotate}{fit},"
             f"fps={FPS},format=yuv420p,setsar=1,setpts=PTS-STARTPTS[v{n}]")
        filters.append(f)
        labels.append(f"[v{n}]")

    filters.append("".join(labels) + f"concat=n={len(shots)}:v=1:a=0[cat]")

    chain = "[cat]"
    if jit["mirror_prob"] > random.random():
        filters.append(f"{chain}hflip[mir]")
        chain = "[mir]"

    if jit["color_shift"]:
        sat = random.uniform(0.96, 1.06)
        gam = random.uniform(0.97, 1.03)
        filters.append(f"{chain}eq=saturation={sat:.3f}:gamma={gam:.3f}[col]")
        chain = "[col]"

    if abs(spd - 1.0) > 0.005:
        filters.append(f"{chain}setpts={1/spd:.4f}*PTS[spd]")
        chain = "[spd]"

    # ---- 3. 烧字幕(三行固定) ----
    # 分行定位，避开中文字体的多行默认行高；长文案自动缩小。
    import unicodedata
    lines = [str(line).strip() for line in cfg["caption"] if str(line).strip()]
    units = max((sum(1 if unicodedata.east_asian_width(c) in "WF" else 0.6
                     for c in line) for line in lines), default=1)
    size = max(1, min(cfg["font_size"], int(W * 0.60 / max(1, units))))
    draws = []
    for row, line in enumerate(lines):
        capfile = Path(tmpdir) / f"cap_{row}.txt"
        capfile.write_text(line, encoding="utf-8")
        draws.append(
            f"drawtext=fontfile='{ff_path(FONT)}':textfile='{ff_path(capfile)}':"
            f"expansion=none:x={cfg['cap_x']}:"
            f"y={cfg['cap_y'] + row * (size + cfg['line_spacing'])}:"
            f"fontsize={size}:fontcolor={cfg['font_color']}:"
            f"borderw={cfg['font_border']}:bordercolor=black@0.85")
    filters.append(chain + (",".join(draws) if draws else "null") + "[txt]")

    vlen = real_total / spd

    # ---- 4. BGM ----
    bgm = random.choice(bgms)
    bdur = duration(bgm)
    boff = random.uniform(0, max(0.0, bdur - vlen - 1)) if bdur > vlen + 1 else 0.0
    ai = len(shots)
    inputs += ["-ss", f"{boff:.2f}", "-i", str(bgm)]

    fo = max(0.0, vlen - cfg["bgm_fadeout"])
    filters.append(f"[{ai}:a]atrim=0:{vlen:.3f},asetpts=PTS-STARTPTS,"
                   f"volume={cfg['bgm_volume']},"
                   f"afade=t=out:st={fo:.2f}:d={cfg['bgm_fadeout']}[aout]")

    out = Path(outdir) / f"v{vid:03d}.mp4"
    cmd = (["ffmpeg", "-y", "-v", "error"] + inputs +
           ["-filter_complex", ";".join(filters),
            "-map", "[txt]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", cfg["preset"], "-crf", str(cfg["crf"]),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", "-t", f"{vlen:.3f}", str(out)])
    sh(cmd)

    # ---- 5. 同步导出封面(首帧) ----
    cover = Path(outdir) / f"v{vid:03d}_cover.jpg"
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(out),
        "-frames:v", "1", "-q:v", "2", str(cover)])

    if usage is not None:
        usage.update(s['key'] for s in shots)

    return {
        "file": out.name,
        "cover": cover.name,
        "shots": len(shots),
        "duration": round(vlen, 2),
        "hook": Path(hook["path"]).name,
        "bgm": bgm.name,
        "mirror": chain != "[cat]",
        "speed": round(spd, 3),
        "unique_clips": len({s['key'] for s in shots}),
        "source_count": len({s['clip'].get('source', s['key']) for s in shots}),
        "timeline": [dict(file=s['clip']['path'], source=s['clip'].get('source'),
                          start=round(s['start'], 3), duration=round(s['len'], 3),
                          source_start=round(s['clip'].get('source_start', 0) + s['start'], 3))
                     for s in shots],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="生成多少条")
    ap.add_argument("--dir", default=".", help="工作目录")
    ap.add_argument("--out", default="out", help="输出目录")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--config", help="JSON 文件,覆盖 CONFIG 里的任意项")
    args = ap.parse_args()

    if args.config and Path(args.config).is_file():
        CONFIG.update(json.loads(Path(args.config).read_text(encoding="utf-8")))

    if args.seed is not None:
        random.seed(args.seed)

    base = Path(args.dir)
    # 旧池已丢失产品画面，不能继续把旧切片放大当作修复。
    if (base / "prep_report.json").exists() and not (base / "pool_policy_v2.json").exists():
        sys.exit("错误: 当前素材池由旧裁切算法生成，可能已误裁产品。"
                 "请用原始视频在新的工作目录重新执行①切片入池，再出片。")
    hooks_f = scan(base / "hooks", VIDEO_EXT)
    clips_f = scan(base / "clips", VIDEO_EXT)
    bgms = scan(base / "bgm", AUDIO_EXT)

    if not hooks_f:
        sys.exit("错误: hooks/ 目录为空。至少放1个剖面特写素材。")
    if not bgms:
        sys.exit("错误: bgm/ 目录为空。")

    if not FONT:
        sys.exit("错误: 系统里没找到中文字体。\n"
                 "  Windows 请确认 C:\\Windows\\Fonts\\msyh.ttc 存在;\n"
                 "  Linux 可执行 apt install fonts-noto-cjk")
    print(f"字体: {FONT}")
    print(f"扫描素材: hooks {len(hooks_f)} / clips {len(clips_f)} / bgm {len(bgms)}")
    min_dur = min(CONFIG["shot_sec"]) * 0.75
    hooks = build_clip_index(hooks_f, min_dur)
    clips = build_clip_index(clips_f, min_dur)
    if not hooks:
        sys.exit(f"错误: 有效素材不足(需时长≥{min_dur:.2f}秒)。"
                 f"\n把'每镜时长'调小,或把'切片时长'调大重新切片。")

    outdir = base / args.out
    outdir.mkdir(exist_ok=True)

    print(f"正文使用全部 {len(hooks) + len(clips)} 个切片，单条不重复，"
          f"同源至少间隔 {CONFIG.get('source_gap', 2)} 镜。")

    manifest = []
    usage = Counter()
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(1, args.n + 1):
            try:
                info = build_variant(i, hooks, clips, bgms, CONFIG, outdir, tmp, usage)
                manifest.append(info)
                print(f"[{i}/{args.n}] {info['file']}  "
                      f"{info['duration']}s / {info['shots']}镜  "
                      f"钩子={info['hook']}")
            except Exception as e:
                print(f"[{i}/{args.n}] 失败: {e}")

    (outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成 {len(manifest)}/{args.n} 条 -> {outdir}/")
    print("每条附带 _cover.jpg 首帧封面,manifest.json 记录了各条的参数组合。")


if __name__ == "__main__":
    main()
