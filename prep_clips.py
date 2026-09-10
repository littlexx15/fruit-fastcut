#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prep_clips.py —— 素材批量切片入池

把一批完整视频切成 1 秒左右的片段,自动裁掉眼睛以上的区域(去身份),
并按画面"钩子强度"自动分流到 hooks/ 和 clips/。

用法:
    python3 prep_clips.py --src raw --out .            # 全自动
    python3 prep_clips.py --src raw --out . --report   # 只出检测报告,不切片
    python3 prep_clips.py --src raw --out . --no-face  # 跳过人脸裁切

目录:
    raw/      放下载好的完整视频
    hooks/    自动生成 —— 剖面特写,给成片当第0帧
    clips/    自动生成 —— 其余镜头
    review/   自动生成 —— 检测存疑的,人工过一眼
"""

import argparse, functools, json, os, shutil, subprocess, sys
from pathlib import Path

import importlib.util
if (importlib.util.find_spec('cv2') is None and sys.version_info[:2] == (3, 12)
        and (Path(__file__).resolve().parent / '.runtime').is_dir()):
    sys.path.insert(0, str(Path(__file__).resolve().parent / '.runtime'))
import cv2
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
print = functools.partial(print, flush=True)

# ============================ CONFIG ============================
CFG = {
    "seg_len": (0.7, 1.1),      # 每个切片时长区间
    "scene_detect": True,       # 先按原片镜头切换分段,再在段内取片(防跳画面)
    "scene_threshold": 0.27,    # 场景切换灵敏度,越小切得越碎
    "boundary_margin": 0.08,    # 距镜头边界的安全余量,躲开转场帧
    "min_scene_len": 0.55,      # 短于此的镜头整段丢弃
    "max_per_scene": 2,         # 单个镜头最多取几片,防止长镜头刷出一堆雷同片
    "min_face_ratio": 0.06,     # 人脸高度至少占画面这个比例,过小的当误检丢弃
    "confirm_window": 2,        # 相邻几个采样帧内要有相近的检出才算数(抗误检)
    "confirm_tol": 0.10,        # "相近"的判定:眼线相差不超过画面高度的这个比例
    "sample_fps": 5,            # 短切片内也有多个采样点
    "detect_width": 480,        # 检测前先缩到这个宽度(只影响速度,不影响裁切精度)
    "eye_ratio": 0.42,          # 人脸框内眼睛所在的相对高度
    "safe_margin": 0.02,        # 裁切线再往下压一点,防漏
    "min_keep_ratio": 0.30,     # 裁完至少要保留原高的30%,否则丢弃该片
    "hook_yellow_min": 0.22,    # 暖色(果肉)占比达标 -> 判为钩子
    "hook_sat_min": 90,         # 饱和度门槛
    "blur_min": 45.0,           # 拉普拉斯方差低于此值判为糊,丢弃
    "crf": 20,
    "preset": "veryfast",

    # --- 按文件名路由 ---
    # 文件名含 match 里任一关键词时,直接决定去向和是否跑人脸检测。
    # 文件名只负责分流；“果肉”素材也可能包含试吃人物。
    # dest: "hooks" | "clips" | "auto"(auto = 按颜色自动判定)
    "routes": [
        {"match": ["果肉", "切果", "滴水", "剖面", "特写"],
         "dest": "hooks", "face": True},
        {"match": ["咀嚼", "试吃", "吃播", "人物", "口播"],
         "dest": "clips", "face": True},
    ],
    "default_route": {"dest": "auto", "face": True},
}
# ================================================================

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".flv", ".ts"}

# ---------- 人脸检测后端:自动适配 opencv 4.x / 5.x ----------
# 4.x: Haar 级联(自带模型)
# 5.x: CascadeClassifier 已移除,改用 FaceDetectorYN(需下载 onnx 模型)
BACKEND = None          # "haar" | "yunet" | None
FRONTAL = PROFILE = None
YUNET = None
FACE_ERR = None

# opencv_zoo 用 Git LFS,raw. 域名只会返回指针文件,必须走 media. 域名
YUNET_URLS = [
    ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
     "face_detection_yunet/face_detection_yunet_2023mar.onnx"),
    ("https://github.com/opencv/opencv_zoo/raw/main/models/"
     "face_detection_yunet/face_detection_yunet_2023mar.onnx"),
]
YUNET_MIN_BYTES = 100_000     # 真模型约 230KB,LFS 指针只有一百多字节
YUNET_FILE = Path(__file__).resolve().parent / "face_detection_yunet.onnx"


def _init_haar():
    global FRONTAL, PROFILE
    d = cv2.data.haarcascades
    FRONTAL = cv2.CascadeClassifier(
        os.path.join(d, "haarcascade_frontalface_default.xml"))
    PROFILE = cv2.CascadeClassifier(
        os.path.join(d, "haarcascade_profileface.xml"))
    if FRONTAL.empty() or PROFILE.empty():
        raise RuntimeError("Haar 模型文件缺失")
    return "haar"


def _init_yunet():
    global YUNET
    if YUNET_FILE.is_file() and YUNET_FILE.stat().st_size < YUNET_MIN_BYTES:
        YUNET_FILE.unlink()          # 上次下到的是 LFS 指针,删掉重来

    if not YUNET_FILE.is_file():
        import urllib.request
        print(f"首次运行,下载人脸模型 {YUNET_FILE.name} (约 230KB)…")
        last = None
        for url in YUNET_URLS:
            try:
                urllib.request.urlretrieve(url, YUNET_FILE)
                if YUNET_FILE.stat().st_size >= YUNET_MIN_BYTES:
                    print("下载完成\n")
                    break
                YUNET_FILE.unlink()
                last = "下到的是 LFS 指针文件,不是模型"
            except Exception as e:
                last = e
        else:
            raise RuntimeError(
                f"模型下载失败 ({last})。\n"
                f"  可手动下载后放到: {YUNET_FILE}\n"
                f"  地址: {YUNET_URLS[0]}")

    # OpenCV 的模型加载器在 Windows 上可能不支持中文路径。
    import tempfile
    with tempfile.TemporaryDirectory(prefix='fruit_face_') as model_dir:
        model_path = Path(model_dir) / 'yunet.onnx'
        shutil.copyfile(YUNET_FILE, model_path)
        YUNET = cv2.FaceDetectorYN_create(str(model_path), "", (320, 320),
                                         score_threshold=0.9)
    return "yunet"


try:
    if hasattr(cv2, "FaceDetectorYN_create"):
        BACKEND = _init_yunet()
    else:
        raise RuntimeError("找不到任何人脸检测接口")
except Exception as e:
    FACE_ERR = (f"人脸检测不可用: {e}\n"
                f"  当前 opencv {getattr(cv2, '__version__', '?')}\n"
                f"  最省事的修法: pip install \"opencv-python-headless<5\"")


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1200:])
    return r.stdout


def probe(path):
    out = sh(["ffprobe", "-v", "error", "-select_streams", "v:0",
              "-show_entries", "stream=width,height",
              "-show_entries", "format=duration",
              "-of", "json", str(path)])
    d = json.loads(out)
    s = d["streams"][0]
    return int(s["width"]), int(s["height"]), float(d["format"]["duration"])


def route_of(name, cfg):
    """按文件名决定去向和是否需要人脸检测。"""
    for r in cfg.get("routes", []):
        if any(k in name for k in r["match"]):
            return r
    return cfg.get("default_route", {"dest": "auto", "face": True})


def confirm(raw, H, window, tol, max_gap=0.4):
    """
    过滤孤立误检:一个检出必须在相邻采样帧里有位置相近的检出才保留。
    Haar 在手、食物、褶皱上常有单帧误报,不过滤会把裁切线拽到画面底部。
    """
    if len(raw) < 2:
        return []
    keep, t_tol = [], H * tol
    for i, (t, y) in enumerate(raw):
        lo, hi = max(0, i - window), min(len(raw), i + window + 1)
        peers = [yy for j, (tt, yy) in enumerate(raw[lo:hi], lo)
                 if j != i and abs(tt - t) <= max_gap + 1e-6
                 and abs(yy - y) <= t_tol]
        if peers:
            keep.append((t, y))
    return keep


def detect_scenes(path, dur, threshold):
    """
    用 ffmpeg 的 scene 滤镜找原片的镜头切换点。
    比 PySceneDetect 快十倍以上,结果一致。
    返回 [(起, 止), ...]
    """
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "info", "-i", str(path),
             "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-",
             "-an", "-f", "null", "-"],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        cuts = []
        for line in r.stderr.splitlines() + r.stdout.splitlines():
            if "pts_time:" in line:
                try:
                    cuts.append(float(line.split("pts_time:")[1].split()[0]))
                except (ValueError, IndexError):
                    pass
        cuts = sorted(set(cuts))
    except Exception:
        cuts = []

    bounds = [0.0] + cuts + [dur]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)
            if bounds[i + 1] - bounds[i] > 0.05]


def detect_faces(frame_bgr, frame_gray):
    """返回人脸框 [(x,y,w,h), ...]。两种后端行为一致。"""
    if BACKEND == "yunet":
        h, w = frame_bgr.shape[:2]
        YUNET.setInputSize((w, h))
        _, faces = YUNET.detect(frame_bgr)
        if faces is None:
            return []
        return [(int(f[0]), int(f[1]), int(f[2]), int(f[3])) for f in faces]

    boxes = []
    for cas in (FRONTAL, PROFILE):
        f = cas.detectMultiScale(frame_gray, scaleFactor=1.1,
                                 minNeighbors=5, minSize=(60, 60))
        boxes.extend(list(f))
    f = PROFILE.detectMultiScale(cv2.flip(frame_gray, 1), scaleFactor=1.1,
                                 minNeighbors=5, minSize=(60, 60))
    W = frame_gray.shape[1]
    for (x, y, w, h) in f:
        boxes.append((W - x - w, y, w, h))
    return boxes


def scan_video(path, sample_fps, eye_ratio):
    """
    通扫全片,返回:
      cut_y      —— 需要从这一行以下开始保留(所有人脸眼线的最高点)
      n_face     —— 检出人脸的帧数
      n_frames   —— 采样帧数
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None, 0, 0, []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(round(fps / sample_fps)))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    raw = []               # [(时间秒, 该帧眼线y)] 未过滤
    cut_y, n_face, n = None, 0, 0
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            n += 1
            dw = CFG["detect_width"]
            scale = dw / frame.shape[1] if frame.shape[1] > dw else 1.0
            small = cv2.resize(frame, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_AREA) if scale < 1.0 else frame
            g = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            boxes = detect_faces(small, g)
            keep_boxes = [(x, y, w, h) for (x, y, w, h) in boxes
                          if h / scale >= H * CFG["min_face_ratio"]]
            if keep_boxes:
                n_face += 1
                frame_eye = max((y + h * eye_ratio) / scale
                                for (x, y, w, h) in keep_boxes)
                raw.append((i / fps, min(frame_eye + H * CFG["safe_margin"], H - 1)))
        i += 1
    cap.release()

    # 保留候选时间点，在每个切片内部确认，防止跨镜头误裁。
    timeline = raw
    n_face = len(timeline)
    cut_y = max((y for _, y in timeline), default=None)
    return cut_y, n_face, n, timeline


def score_frame(bgr):
    """给一帧打分:暖色占比(果肉) + 清晰度。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    warm = ((h >= 10) & (h <= 38) & (s >= CFG["hook_sat_min"]) & (v >= 110))
    yellow_ratio = float(warm.mean())
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return yellow_ratio, blur


def score_segment(path):
    """取切片中间帧打分。"""
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, n // 2))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return 0.0, 0.0
    return score_frame(frame)


def plan_segments(scenes, cfg):
    """
    在每个镜头内部规划取片位置。核心规则:
      · 切片永不跨越镜头边界 -> 不会出现跳画面
      · 距边界留安全余量 -> 躲开转场/运动模糊帧
      · 单镜头最多取 max_per_scene 片 -> 长镜头不刷雷同片
    """
    import random
    m = cfg["boundary_margin"]
    lo, hi = cfg["seg_len"]
    plan, stat = [], {"too_short": 0, "scenes": len(scenes)}

    for (s0, s1) in scenes:
        a, b = s0 + m, s1 - m
        usable = b - a
        if usable < max(lo, cfg["min_scene_len"]):
            stat["too_short"] += 1
            continue

        n = min(cfg["max_per_scene"], max(1, int(usable // lo)))
        if n == 1:
            L = min(random.uniform(lo, hi), usable)
            st = a + random.uniform(0, usable - L)
            plan.append((st, L))
        else:
            # 在镜头内均匀分布,彼此不重叠
            slot = usable / n
            for k in range(n):
                L = min(random.uniform(lo, hi), slot)
                st = a + k * slot + random.uniform(0, max(0.0, slot - L))
                plan.append((st, L))
    return plan, stat


def slice_video(src, timeline, W, H, dur, outdir, stem, cfg):
    """按规划好的位置切片,裁切线按每片自己的时间窗单独算。"""
    import random

    if cfg.get("scene_detect", True):
        scenes = detect_scenes(src, dur, cfg["scene_threshold"])
        plan, stat = plan_segments(scenes, cfg)
    else:
        plan, stat = [], {"scenes": 0, "too_short": 0}
        t = 0.0
        while t < dur - 0.5:
            L = random.uniform(*cfg["seg_len"])
            if t + L > dur:
                break
            plan.append((t, L))
            t += L

    made, skipped = [], 0
    stat['segments'] = []
    for idx, (t, L) in enumerate(plan):
        # 该片段时间窗内的最低眼线
        local = [(ts, y) for ts, y in timeline if t <= ts < t + L]
        confirmed = confirm(local, H, cfg["confirm_window"], cfg["confirm_tol"],
                            2 / cfg["sample_fps"])
        eyes = [y for _, y in confirmed]
        cut = max(eyes) if eyes else None

        if cut is not None:
            y0 = int(cut)
            keep = H - y0
            if keep < H * cfg["min_keep_ratio"]:
                skipped += 1
                continue
        else:
            y0, keep = 0, H
        y0 -= y0 % 2
        keep -= keep % 2

        out = Path(outdir) / f"{stem}_{idx:03d}.mp4"
        vf = f"crop={W}:{keep}:0:{y0}" if cut is not None else "null"
        try:
            sh(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-t", f"{L:.2f}",
                "-i", str(src), "-vf", vf, "-an",
                "-c:v", "libx264", "-preset", cfg["preset"], "-crf", str(cfg["crf"]),
                "-pix_fmt", "yuv420p", "-y", str(out)])
            made.append(out)
            stat['segments'].append({'file': out.name, 'start': t, 'duration': L,
                                     'crop_y': y0, 'source_size': [W, H],
                                     'confirmed_samples': len(confirmed)})
        except Exception:
            pass
    return made, skipped, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="raw")
    ap.add_argument("--out", default=".")
    ap.add_argument("--report", action="store_true", help="只检测,不切片")
    ap.add_argument("--no-face", action="store_true", help="跳过人脸裁切")
    ap.add_argument("--config", help="JSON 文件,覆盖 CFG 里的任意项")
    args = ap.parse_args()

    if args.config and Path(args.config).is_file():
        CFG.update(json.loads(Path(args.config).read_text(encoding="utf-8")))

    src = Path(args.src)
    files = sorted([f for f in src.iterdir() if f.suffix.lower() in VIDEO_EXT]) \
        if src.is_dir() else []
    if not files:
        sys.exit(f"错误: {src}/ 里没找到视频")

    base = Path(args.out)
    if not args.report and any(any((base / sub).glob('*.mp4'))
                               for sub in ('hooks', 'clips', 'review')):
        sys.exit("错误: 工作目录已有切片。请选新的空工作目录，避免混入旧误裁素材。")
    hooks_d, clips_d, rev_d = base / "hooks", base / "clips", base / "review"
    tmp_d = base / "_tmp"
    for d in (hooks_d, clips_d, rev_d, tmp_d):
        d.mkdir(parents=True, exist_ok=True)

    if FACE_ERR and not args.no_face:
        sys.exit(FACE_ERR)

    print(f"待处理 {len(files)} 条   人脸后端: {BACKEND or '无'}\n")
    log = []
    n_hook = n_clip = n_rev = n_drop = 0

    for f in files:
        try:
            W, H, dur = probe(f)
        except Exception as e:
            print(f"× {f.name}: 读取失败"); continue

        rt = route_of(f.name, CFG)
        need_face = rt["face"] and not args.no_face and FACE_ERR is None

        cut_y, n_face, n_smp, timeline = (None, 0, 0, [])
        if need_face:
            cut_y, n_face, n_smp, timeline = scan_video(f, CFG["sample_fps"], CFG["eye_ratio"])

        rate = (n_face / n_smp * 100) if n_smp else 0
        dest_txt = {"hooks": "-> hooks", "clips": "-> clips",
                    "auto": "-> 按颜色自动分"}[rt["dest"]]
        if not need_face:
            note = f"产品素材,跳过人脸检测   {dest_txt}"
        elif cut_y is not None:
            keep_pct = (H - cut_y) / H * 100
            note = (f"人脸 {n_face}/{n_smp}帧({rate:.0f}%) -> y={int(cut_y)} "
                    f"以下保留 {keep_pct:.0f}%   {dest_txt}")
        else:
            note = f"未检出人脸({n_smp}帧采样),不裁切   {dest_txt}"
        print(f"● {f.name}  {W}x{H} {dur:.1f}s")
        print(f"  {note}")

        log.append({"file": f.name, "size": f"{W}x{H}", "dur": round(dur, 1),
                    "face_frames": n_face, "sampled": n_smp,
                    "cut_y": int(cut_y) if cut_y else None,
                    "route": rt["dest"], "face_scanned": need_face})

        if args.report:
            continue

        segs, skipped, stat = slice_video(f, timeline, W, H, dur, tmp_d, f.stem, CFG)
        log[-1]['segments'] = stat['segments']
        if stat["scenes"]:
            print(f"  原片 {stat['scenes']} 个镜头,{stat['too_short']} 个过短丢弃")

        for s in segs:
            yr, bl = score_segment(s)
            if bl < CFG["blur_min"]:
                s.unlink(); n_drop += 1; continue
            if rt["dest"] == "hooks":
                shutil.move(str(s), hooks_d / s.name); n_hook += 1
            elif rt["dest"] == "clips":
                shutil.move(str(s), clips_d / s.name); n_clip += 1
            elif yr >= CFG["hook_yellow_min"]:
                shutil.move(str(s), hooks_d / s.name); n_hook += 1
            elif yr >= CFG["hook_yellow_min"] * 0.5:
                shutil.move(str(s), rev_d / s.name); n_rev += 1
            else:
                shutil.move(str(s), clips_d / s.name); n_clip += 1
        msg = f"  切出 {len(segs)} 片"
        if skipped:
            msg += f",{skipped} 片因人脸占比过大跳过"
        print(msg + "\n")

    shutil.rmtree(tmp_d, ignore_errors=True)
    (base / "prep_report.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.report:
        (base / "pool_policy_v2.json").write_text(json.dumps({
            "version": 2, "source": str(src.resolve()),
            "detector": BACKEND, "face_disabled": args.no_face,
            "policy": "segment_confirmed_faces_only"
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print("=" * 46)
        print(f"hooks/   {n_hook:4d}  (剖面特写,自动判定)")
        print(f"clips/   {n_clip:4d}  (常规镜头)")
        print(f"review/  {n_rev:4d}  (存疑,人工过一眼再分)")
        print(f"丢弃     {n_drop:4d}  (模糊)")
        print("\n检测明细见 prep_report.json")


if __name__ == "__main__":
    main()
