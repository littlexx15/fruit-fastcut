#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
混剪工具 —— prep_clips.py + batch_cut.py 的图形界面

双击运行,或命令行: python3 混剪工具.py
需要 prep_clips.py 和 batch_cut.py 与本文件在同一目录。
"""

import json, os, queue, subprocess, sys, threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

HERE = Path(__file__).resolve().parent
PREP = HERE / "prep_clips.py"
CUT = HERE / "batch_cut.py"


def worker_command(script):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--worker', script.stem]
    return [sys.executable, str(script)]

BG = "#1e1f22"
FG = "#e8e8e8"
ACC = "#4a9eff"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("混剪工具")
        self.geometry("900x780")
        self.configure(bg=BG)
        self.proc = None
        self.q = queue.Queue()

        self._style()
        self._build()
        self.after(80, self._drain)

    # ---------------- 外观 ----------------
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure(".", background=BG, foreground=FG, fieldbackground="#2b2d31",
                    bordercolor="#3a3d43", lightcolor=BG, darkcolor=BG)
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background="#2b2d31", foreground=FG,
                    padding=(20, 9), borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", BG)],
              foreground=[("selected", ACC)])
        s.configure("TLabelframe", background=BG, foreground=FG, borderwidth=1)
        s.configure("TLabelframe.Label", background=BG, foreground="#9aa0a6")
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("TButton", background="#33363b", foreground=FG,
                    borderwidth=0, padding=(14, 7), focuscolor=BG)
        s.map("TButton", background=[("active", "#3f434a")])
        s.configure("Go.TButton", background=ACC, foreground="#0b0c0e",
                    font=("", 10, "bold"), padding=(20, 9))
        s.map("Go.TButton", background=[("active", "#63b0ff"),
                                        ("disabled", "#3a3d43")])
        s.configure("TCheckbutton", background=BG, foreground=FG)
        s.map("TCheckbutton", background=[("active", BG)])
        s.configure("TRadiobutton", background=BG, foreground=FG)
        s.map("TRadiobutton", background=[("active", BG)])
        s.configure("TEntry", insertcolor=FG)
        s.configure("TSpinbox", insertcolor=FG, arrowcolor=FG)

    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=False, padx=14, pady=(12, 0))
        self.tab_prep(nb)
        self.tab_cut(nb)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=14, pady=(10, 4))
        self.btn = ttk.Button(bar, text="开始", style="Go.TButton", command=self.run)
        self.btn.pack(side="left")
        self.stop = ttk.Button(bar, text="中止", command=self.kill, state="disabled")
        self.stop.pack(side="left", padx=8)
        self.status = ttk.Label(bar, text="就绪", foreground="#9aa0a6")
        self.status.pack(side="left", padx=14)
        ttk.Button(bar, text="打开输出目录", command=self.open_out).pack(side="right")

        self.log = tk.Text(self, bg="#151619", fg="#c8ccd0", insertbackground=FG,
                           relief="flat", font=("Menlo", 10), wrap="word",
                           padx=12, pady=10)
        self.log.pack(fill="both", expand=True, padx=14, pady=(4, 14))
        self.log.tag_config("err", foreground="#ff6b6b")
        self.log.tag_config("ok", foreground="#5ed17f")
        self.nb = nb

    # ---------------- 页1:切片入池 ----------------
    def tab_prep(self, nb):
        f = tk.Frame(nb, bg=BG)
        nb.add(f, text="  ①  切片入池  ")

        self.p_raw = tk.StringVar()
        self.p_out = tk.StringVar()
        self._picker(f, "原始视频目录", self.p_raw, 0,
                     "把下载好的完整视频全放这里")
        self._picker(f, "工作目录", self.p_out, 1,
                     "会在这里生成 hooks/ clips/ review/")

        g = ttk.Labelframe(f, text=" 参数 ", padding=12)
        g.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(12, 6))

        self.seg_min = tk.DoubleVar(value=0.7)
        self.seg_max = tk.DoubleVar(value=1.1)
        self.eye = tk.DoubleVar(value=0.42)
        self.yellow = tk.DoubleVar(value=0.22)

        self._num(g, "切片时长", self.seg_min, 0, 0, 0.3, 3.0, 0.1,
                  second=self.seg_max, unit="秒")
        self._num(g, "眼线位置", self.eye, 1, 0, 0.20, 0.60, 0.02,
                  tip="人脸框内眼睛的相对高度。调小=裁得更狠更安全")
        self._num(g, "钩子暖色阈值", self.yellow, 2, 0, 0.05, 0.60, 0.02,
                  tip="果肉色占比超过它就进 hooks。换品要调")

        self.no_face = tk.BooleanVar(value=False)
        self.report = tk.BooleanVar(value=False)
        ttk.Checkbutton(g, text="跳过人脸裁切", variable=self.no_face)\
            .grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Checkbutton(g, text="只出检测报告,先不切片(建议首次勾选)",
                        variable=self.report)\
            .grid(row=3, column=1, columnspan=4, sticky="w", pady=(10, 0))

        g3 = ttk.Labelframe(f, text=" 镜头识别(防跳画面) ", padding=12)
        g3.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=6)

        self.scene_on = tk.BooleanVar(value=True)
        self.scene_th = tk.DoubleVar(value=0.27)
        self.per_scene = tk.IntVar(value=2)
        self.margin = tk.DoubleVar(value=0.08)

        ttk.Checkbutton(g3, text="先识别原片镜头切换,切片只在镜头内部取"
                                 "(强烈建议开启)",
                        variable=self.scene_on)\
            .grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))
        self._num(g3, "切换灵敏度", self.scene_th, 1, 0, 0.05, 0.60, 0.02,
                  tip="越小切得越碎。源片剪得快就调小")
        self._num(g3, "单镜头最多取", self.per_scene, 2, 0, 1, 8, 1,
                  integer=True, unit="片",
                  tip="防止长镜头刷出一堆雷同片")
        self._num(g3, "边界安全余量", self.margin, 3, 0, 0.0, 0.5, 0.02,
                  unit="秒", tip="躲开转场帧。调大更保险但更费素材")

        f.columnconfigure(1, weight=1)

    # ---------------- 页2:批量出片 ----------------
    def tab_cut(self, nb):
        f = tk.Frame(nb, bg=BG)
        nb.add(f, text="  ②  批量出片  ")

        repaired = HERE / '板栗红薯_修复素材池_v2'
        self.c_dir = tk.StringVar(value=str(repaired) if
                                  (repaired / 'pool_policy_v2.json').exists() else '')
        self._picker(f, "工作目录", self.c_dir, 0,
                     "含 hooks/ clips/ bgm/ 的那个目录")

        g = ttk.Labelframe(f, text=" 屏幕文案(三行,固定不动) ", padding=12)
        g.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(12, 6))
        self.cap = []
        for i, d in enumerate(["都去吃这个红心蜜柚",
                               "就喜欢这种爆汁的清甜感",
                               "越吃越上头巨好吃"]):
            v = tk.StringVar(value=d)
            e = ttk.Entry(g, textvariable=v, font=("", 11))
            e.grid(row=i, column=0, sticky="ew", pady=3, ipady=3)
            self.cap.append(v)
        g.columnconfigure(0, weight=1)
        ttk.Label(g, text="emoji 会显示成方框,建议不用",
                  foreground="#7a7f85").grid(row=3, column=0, sticky="w", pady=(6, 0))

        g2 = ttk.Labelframe(f, text=" 出片设置 ", padding=12)
        g2.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=6)

        self.n = tk.IntVar(value=20)
        self.shot_min = tk.DoubleVar(value=0.7)
        self.shot_max = tk.DoubleVar(value=0.9)
        self.tot_min = tk.DoubleVar(value=35)
        self.tot_max = tk.DoubleVar(value=40)
        self.aspect = tk.StringVar(value="v")

        self._num(g2, "生成条数", self.n, 0, 0, 1, 500, 1, integer=True, unit="条")
        self._num(g2, "每镜时长", self.shot_min, 1, 0, 0.4, 3.0, 0.05,
                  second=self.shot_max, unit="秒")
        self._num(g2, "成片总长", self.tot_min, 2, 0, 10, 90, 1,
                  second=self.tot_max, unit="秒")

        r = tk.Frame(g2, bg=BG)
        r.grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Label(r, text="画幅").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(r, text="竖屏 1080×1920", variable=self.aspect,
                        value="v").pack(side="left", padx=(0, 16))
        ttk.Radiobutton(r, text="横屏 1920×1080（顺时针90°）", variable=self.aspect,
                        value="h").pack(side="left")
        ttk.Label(r, text="  裁脸后铺满，无黑边",
                  foreground="#7a7f85").pack(side="left", padx=10)

        f.columnconfigure(1, weight=1)

    # ---------------- 控件辅助 ----------------
    def _picker(self, parent, label, var, row, tip=""):
        box = tk.Frame(parent, bg=BG)
        box.grid(row=row, column=0, columnspan=3, sticky="ew", padx=12,
                 pady=(12, 0))
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text=label, width=14).grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=var).grid(row=0, column=1, sticky="ew",
                                              ipady=3)
        ttk.Button(box, text="浏览…",
                   command=lambda: self._browse(var)).grid(row=0, column=2,
                                                           padx=(10, 0))
        if tip:
            ttk.Label(box, text=tip, foreground="#7a7f85")\
                .grid(row=1, column=1, sticky="w", pady=(3, 0))

    def _browse(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    def _num(self, parent, label, var, row, col, lo, hi, step,
             second=None, unit="", integer=False, tip=""):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w",
                                           pady=3, padx=(0, 10))
        fmt = "%.0f" if integer else "%.2f"
        sp = ttk.Spinbox(parent, from_=lo, to=hi, increment=step,
                         textvariable=var, width=7, format=fmt)
        sp.grid(row=row, column=col + 1, sticky="w")
        c = col + 2
        if second is not None:
            ttk.Label(parent, text="—").grid(row=row, column=c, padx=6)
            ttk.Spinbox(parent, from_=lo, to=hi, increment=step,
                        textvariable=second, width=7,
                        format=fmt).grid(row=row, column=c + 1, sticky="w")
            c += 2
        txt = unit + (("   " + tip) if tip else "")
        if txt:
            ttk.Label(parent, text=txt, foreground="#7a7f85")\
                .grid(row=row, column=c, sticky="w", padx=8)

    # ---------------- 运行 ----------------
    def w(self, txt, tag=None):
        self.log.insert("end", txt, tag)
        self.log.see("end")

    def run(self):
        if self.proc:
            return
        self.log.delete("1.0", "end")
        idx = self.nb.index(self.nb.select())
        try:
            cmd, cfg, wd = self._build_cmd(idx)
        except ValueError as e:
            messagebox.showwarning("检查一下", str(e))
            return

        Path(wd).mkdir(parents=True, exist_ok=True)
        cfgp = Path(wd) / "_gui_config.json"
        cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        cmd += ["--config", str(cfgp)]

        self.w("$ " + " ".join(cmd) + "\n\n")
        self.btn.config(state="disabled")
        self.stop.config(state="normal")
        self.status.config(text="运行中…", foreground=ACC)
        threading.Thread(target=self._worker, args=(cmd, wd), daemon=True).start()

    def _build_cmd(self, idx):
        if idx == 0:
            raw, out = self.p_raw.get().strip(), self.p_out.get().strip()
            if not raw or not Path(raw).is_dir():
                raise ValueError("请选择原始视频目录")
            if not out:
                out = str(Path(raw).parent)
                self.p_out.set(out)
            if not PREP.is_file():
                raise ValueError(f"找不到 {PREP.name},请和本程序放在同一目录")
            cmd = worker_command(PREP) + ["--src", raw, "--out", out]
            if self.no_face.get():
                cmd.append("--no-face")
            if self.report.get():
                cmd.append("--report")
            cfg = {
                "seg_len": [self.seg_min.get(), self.seg_max.get()],
                "eye_ratio": self.eye.get(),
                "hook_yellow_min": self.yellow.get(),
                "scene_detect": self.scene_on.get(),
                "scene_threshold": self.scene_th.get(),
                "max_per_scene": self.per_scene.get(),
                "boundary_margin": self.margin.get(),
            }
            return cmd, cfg, out

        d = self.c_dir.get().strip() or self.p_out.get().strip()
        if not d or not Path(d).is_dir():
            raise ValueError("请选择工作目录")
        for sub in ("hooks", "bgm"):
            p = Path(d) / sub
            if not p.is_dir() or not any(p.iterdir()):
                raise ValueError(f"{sub}/ 不存在或是空的\n\n"
                                 f"先跑①切片入池,bgm/ 需要你自己放几首音乐")
        if not CUT.is_file():
            raise ValueError(f"找不到 {CUT.name},请和本程序放在同一目录")
        w, h = (1080, 1920) if self.aspect.get() == "v" else (1920, 1080)
        cfg = {
            "caption": [v.get() for v in self.cap],
            "width": w, "height": h,
            "shot_sec": [self.shot_min.get(), self.shot_max.get()],
            "total_sec": [self.tot_min.get(), self.tot_max.get()],
        }
        cmd = worker_command(CUT) + ["--dir", d, "--n", str(self.n.get())]
        return cmd, cfg, d

    def _worker(self, cmd, wd):
        try:
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"   # Windows 默认 GBK,会乱码
            env["PYTHONUTF8"] = "1"
            self.proc = subprocess.Popen(
                cmd, cwd=wd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            for line in self.proc.stdout:
                self.q.put(("log", line))
            rc = self.proc.wait()
            self.q.put(("done", rc))
        except Exception as e:
            self.q.put(("log", f"\n启动失败: {e}\n"))
            self.q.put(("done", -1))

    def _drain(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    tag = "err" if ("错误" in val or "失败" in val or "×" in val) else None
                    self.w(val, tag)
                else:
                    self.proc = None
                    self.btn.config(state="normal")
                    self.stop.config(state="disabled")
                    if val == 0:
                        self.w("\n完成\n", "ok")
                        self.status.config(text="完成", foreground="#5ed17f")
                    else:
                        self.status.config(text=f"退出码 {val}", foreground="#ff6b6b")
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def kill(self):
        if self.proc:
            self.proc.terminate()
            self.w("\n已中止\n", "err")

    def open_out(self):
        d = self.c_dir.get().strip() or self.p_out.get().strip()
        if not d:
            return
        p = Path(d) / "out"
        p = p if p.is_dir() else Path(d)
        if sys.platform == "darwin":
            subprocess.run(["open", str(p)])
        elif os.name == "nt":
            os.startfile(str(p))
        else:
            subprocess.run(["xdg-open", str(p)])


if __name__ == "__main__":
    App().mainloop()
