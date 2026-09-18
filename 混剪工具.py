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
        s.configure('TCombobox', fieldbackground='#2b2d31', foreground=FG, arrowcolor=FG)
        s.map('TCombobox', fieldbackground=[('readonly', '#2b2d31')],
              foreground=[('readonly', FG)], selectbackground=[('readonly', '#2b2d31')],
              selectforeground=[('readonly', FG)])
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
        self.p_raw.trace_add('write', self._suggest_workdir)
        self._picker(f, "原始视频目录", self.p_raw, 0,
                     "把下载好的完整视频全放这里")
        self._picker(f, "工作目录", self.p_out, 1,
                     "自动使用原目录名-切片，可手动修改；完成后同步到批量出片")

        g = ttk.Labelframe(f, text=" 参数 ", padding=12)
        g.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(12, 6))

        self.seg_min = tk.DoubleVar(value=0.7)
        self.seg_max = tk.DoubleVar(value=1.1)
        self.eye = tk.DoubleVar(value=0.42)

        self._num(g, "切片时长", self.seg_min, 0, 0, 0.3, 3.0, 0.1,
                  second=self.seg_max, unit="秒")
        self._num(g, "眼线位置", self.eye, 1, 0, 0.20, 0.60, 0.02,
                  tip="人脸框内眼睛的相对高度。调小=裁得更狠更安全")

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
                     "含 clips/ 的工作目录；兼容旧 hooks/ 和 review/ 素材")

        self.c_bgm = tk.StringVar()
        self.bgm_enabled = tk.BooleanVar(value=True)
        self._picker(f, "背景音乐目录", self.c_bgm, 1,
                     "可选：留空不配乐；选择目录后每条随机一首",
                     button_text="选择音乐文件夹…")

        self.sfx_enabled = tk.BooleanVar(value=False)
        self.sfx_path = tk.StringVar()
        self.sfx_volume = tk.DoubleVar(value=70)
        self.sfx_gap = tk.DoubleVar(value=2.5)
        soundbar = tk.Frame(f, bg=BG)
        soundbar.grid(row=2, column=0, columnspan=3, sticky='ew', padx=12, pady=(8, 0))
        ttk.Checkbutton(soundbar, text='添加背景音乐', variable=self.bgm_enabled).pack(side='left', padx=(0,12))
        ttk.Checkbutton(soundbar, text='果肉画面自动加音效', variable=self.sfx_enabled).pack(side='left')
        ttk.Button(soundbar, text='音效设置…', command=self._sound_settings).pack(side='left', padx=10)
        ttk.Label(soundbar, text='音效可单独使用', foreground='#7a7f85').pack(side='left')

        g = ttk.Labelframe(f, text=" 屏幕文案(三行,固定不动) ", padding=12)
        g.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(12, 6))
        self.cap = []
        self.caption_font = tk.StringVar(value='')
        self.batch_caption_enabled = tk.BooleanVar(value=False)
        self.batch_caption_shuffle = tk.BooleanVar(value=False)
        self.batch_caption_text = ''
        for i, d in enumerate(["都去吃这个红心蜜柚",
                               "就喜欢这种爆汁的清甜感",
                               "越吃越上头巨好吃"]):
            v = tk.StringVar(value=d)
            e = ttk.Entry(g, textvariable=v, font=("", 11))
            e.grid(row=i, column=0, sticky="ew", pady=3, ipady=3)
            self.cap.append(v)
        g.columnconfigure(0, weight=1)
        fontbar = ttk.Frame(g)
        fontbar.grid(row=3, column=0, sticky='ew', pady=(6, 0))
        ttk.Label(fontbar, text="支持粘贴彩色 emoji，如 🍊 😋 ❤️",
                  foreground="#7a7f85").pack(side='left')
        ttk.Button(fontbar, text='选择字体 / 预览…', command=self._font_settings).pack(side='right')
        batchbar = ttk.Frame(g)
        batchbar.grid(row=4,column=0,sticky='ew',pady=(4,0))
        ttk.Checkbutton(batchbar,text='每条视频使用不同文案',variable=self.batch_caption_enabled).pack(side='left')
        ttk.Button(batchbar,text='粘贴批量文案…',command=self._batch_caption_settings).pack(side='left',padx=10)
        self.caption_count = tk.StringVar(value='已保存 0 组')
        ttk.Label(batchbar,textvariable=self.caption_count,foreground='#9aa0a6').pack(side='left')

        g2 = ttk.Labelframe(f, text=" 出片设置 ", padding=12)
        g2.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=6)

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
        ttk.Radiobutton(r, text="横屏 1920×1080", variable=self.aspect,
                        value="h").pack(side="left")
        ttk.Label(r, text="  自动旋转、等比缩放铺满",
                  foreground="#7a7f85").pack(side="left", padx=10)

        f.columnconfigure(1, weight=1)

    # ---------------- 控件辅助 ----------------
    def _batch_caption_settings(self):
        from caption_pool import parse_captions
        if getattr(self,'_batch_window',None) and self._batch_window.winfo_exists():
            self._batch_window.lift();return
        win=self._batch_window=tk.Toplevel(self)
        win.title('批量文案');win.transient(self);win.configure(bg=BG)
        win.geometry('720x620');win.minsize(560,400)
        box=ttk.Frame(win,padding=14);box.pack(fill='both',expand=True)
        ttk.Label(box,text='每组1～3行，组间空一行；整组重复的文案自动去重。').pack(anchor='w')
        frame=ttk.Frame(box);frame.pack(fill='both',expand=True,pady=10)
        editor=tk.Text(frame,wrap='word',undo=True,bg='#2b2d31',fg=FG,insertbackground=FG,font=('',11))
        scroll=ttk.Scrollbar(frame,command=editor.yview);editor.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');editor.pack(side='left',fill='both',expand=True)
        editor.insert('1.0',self.batch_caption_text)
        count=tk.StringVar();ttk.Label(box,textvariable=count,wraplength=660).pack(anchor='w')
        shuffled=tk.BooleanVar(value=self.batch_caption_shuffle.get())
        ttk.Checkbutton(box,text='打乱文案顺序（默认按粘贴顺序分配，不重复）',variable=shuffled).pack(anchor='w',pady=8)
        def update(*_):
            try:count.set(f'已识别 {len(parse_captions(editor.get("1.0","end-1c")))} 组不同文案')
            except ValueError as exc:count.set(str(exc))
            editor.edit_modified(False)
        editor.bind('<<Modified>>',lambda e: update() if editor.edit_modified() else None)
        def save(match_count=False):
            text=editor.get('1.0','end-1c')
            try:
                groups=parse_captions(text)
                if not groups:raise ValueError('请先粘贴文案，每组之间空一行')
            except ValueError as exc:messagebox.showwarning('检查文案',str(exc),parent=win);return
            self.batch_caption_text=text;self.batch_caption_enabled.set(True)
            self.batch_caption_shuffle.set(shuffled.get());self.caption_count.set(f'已保存 {len(groups)} 组')
            if match_count:self.n.set(len(groups))
            win.destroy()
        buttons=ttk.Frame(box);buttons.pack(fill='x')
        ttk.Button(buttons,text='保存，并按组数生成',command=lambda:save(True)).pack(side='right')
        ttk.Button(buttons,text='保存文案',command=save).pack(side='right',padx=8)
        update()

    def _font_settings(self):
        from font_selection import installed_fonts, resolve_font
        from batch_cut import FONT
        from caption_render import render_caption
        from PIL import Image, ImageTk, ImageOps
        import tempfile
        if getattr(self, '_font_window', None) and self._font_window.winfo_exists():
            self._font_window.lift()
            return
        win = self._font_window = tk.Toplevel(self)
        win.title('选择字幕字体')
        win.configure(bg=BG);win.transient(self);win.resizable(False, False)
        box = ttk.Frame(win, padding=16);box.pack(fill='both', expand=True)
        fonts = installed_fonts()
        selected = tk.StringVar(value=self.caption_font.get() or FONT or '')
        choice = tk.StringVar(value=next((k for k,v in fonts.items()
                                        if os.path.normcase(v) == os.path.normcase(selected.get())), '自选字体'))
        ttk.Label(box, text='已安装的中文字体').grid(row=0,column=0,sticky='w')
        combo = ttk.Combobox(box, textvariable=choice, values=list(fonts), state='readonly', width=55)
        combo.grid(row=1,column=0,sticky='ew',pady=8)
        ttk.Label(box,textvariable=selected,wraplength=620,foreground='#9aa0a6').grid(row=2,column=0,columnspan=2,sticky='w')
        ttk.Label(box,text='当前文案预览（画面上方区域，布局与成片一致）').grid(row=3,column=0,columnspan=2,sticky='w',pady=(12,4))
        preview = ttk.Label(box);preview.grid(row=4,column=0,columnspan=2)
        error = tk.StringVar()
        ttk.Label(box,textvariable=error,foreground='#ff6b6b',wraplength=620).grid(row=5,column=0,columnspan=2,sticky='w')
        def redraw(*_):
            try:
                path=resolve_font(selected.get(),FONT)
                width,height=(1080,1920) if self.aspect.get()=='v' else (1920,1080)
                with tempfile.TemporaryDirectory() as td:
                    file=Path(td)/'preview.png'
                    lines=[v.get().strip() for v in self.cap if v.get().strip()]
                    if self.batch_caption_enabled.get():
                        from caption_pool import parse_captions
                        groups=parse_captions(self.batch_caption_text)
                        if groups:lines=groups[0]
                    render_caption(lines,width,height,58,path,'white',file)
                    with Image.open(file) as rendered:
                        crop=rendered.crop((0,0,width,round(height*.25)))
                        background=Image.new('RGBA',crop.size,'#45494f');background.alpha_composite(crop)
                        im=ImageOps.contain(background.convert('RGB'),(640,240))
                        preview.image=ImageTk.PhotoImage(im)
                        preview.configure(image=preview.image)
                error.set('')
            except (ValueError,OSError) as exc:error.set(str(exc))
        def changed(*_):
            if choice.get() in fonts:selected.set(fonts[choice.get()]);redraw()
        combo.bind('<<ComboboxSelected>>',changed)
        def browse():
            path=filedialog.askopenfilename(parent=win,title='选择中文字体文件',filetypes=[('字体文件','*.ttf *.otf *.ttc')])
            if path:selected.set(path);choice.set('自选字体');redraw()
        ttk.Button(box,text='选择字体文件…',command=browse).grid(row=1,column=1,padx=(10,0))
        def apply():
            try:self.caption_font.set(resolve_font(selected.get(),FONT))
            except ValueError as exc:error.set(str(exc));return
            win.destroy()
        ttk.Button(box,text='应用字体',command=apply).grid(row=6,column=1,pady=(12,0))
        ttk.Label(box,text='中文字体影响文案；彩色 emoji 仍单独渲染。',foreground='#9aa0a6').grid(row=6,column=0,sticky='w')
        redraw()

    def _sound_settings(self):
        if getattr(self, '_sound_window', None) and self._sound_window.winfo_exists():
            self._sound_window.lift()
            return
        win = self._sound_window = tk.Toplevel(self)
        win.title('果肉音效设置')
        win.configure(bg=BG)
        win.transient(self)
        win.resizable(True, False)
        box = ttk.Frame(win, padding=18)
        box.pack(fill='both', expand=True)
        box.columnconfigure(0, weight=1)
        ttk.Checkbutton(box, text='启用：果肉画面自动添加音效', variable=self.sfx_enabled).grid(row=0, column=0, sticky='w')
        ttk.Entry(box, textvariable=self.sfx_path, width=65).grid(row=1, column=0, columnspan=3, sticky='ew', pady=12)
        def select_file():
            path = filedialog.askopenfilename(parent=win, title='选择吃水果音效',
                filetypes=[('音频', '*.wav *.mp3 *.m4a *.aac *.flac *.ogg')])
            if path: self.sfx_path.set(path)
        def select_folder():
            path = filedialog.askdirectory(parent=win, title='选择音效文件夹')
            if path: self.sfx_path.set(path)
        ttk.Button(box, text='选择音效文件…', command=select_file).grid(row=2, column=0, sticky='w')
        ttk.Button(box, text='选择音效文件夹…', command=select_folder).grid(row=2, column=1, sticky='w')
        settings = ttk.Frame(box)
        settings.grid(row=3, column=0, columnspan=3, sticky='ew', pady=12)
        self._num(settings, '音效音量', self.sfx_volume, 0, 0, 0, 200, 5, unit='%')
        self._num(settings, '最短触发间隔', self.sfx_gap, 1, 0, 0, 60, .5, unit='秒')
        ttk.Label(box, text='文件夹内随机选音效；从声音开头播放，最长不超过当前镜头。\n识别可能漏选或误选；匹配果肉展示，不识别真实咬下动作。',
                  foreground='#9aa0a6').grid(row=4, column=0, columnspan=3, sticky='w')
        ttk.Button(box, text='完成', command=win.destroy).grid(row=5, column=2, pady=(12, 0))

    def _picker(self, parent, label, var, row, tip="", button_text="浏览…"):
        box = tk.Frame(parent, bg=BG)
        box.grid(row=row, column=0, columnspan=3, sticky="ew", padx=12,
                 pady=(12, 0))
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text=label, width=14).grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=var).grid(row=0, column=1, sticky="ew",
                                              ipady=3)
        ttk.Button(box, text=button_text,
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
    def _suggest_workdir(self, *_):
        raw = self.p_raw.get().strip()
        if raw:
            path = Path(raw)
            self.p_out.set(str(path.parent / (path.name + '-切片')))

    def _sync_completed_pool(self, code):
        target = getattr(self, '_pending_pool', None)
        self._pending_pool = None
        if code == 0 and target and any((Path(target) / 'clips').glob('*.mp4')):
            self.c_dir.set(target)
            self.w(f'已同步批量出片工作目录：{target}\n', 'ok')

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
        except (ValueError, tk.TclError) as e:
            messagebox.showwarning("检查一下", str(e))
            return

        Path(wd).mkdir(parents=True, exist_ok=True)
        cfgp = Path(wd) / "_gui_config.json"
        cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        cmd += ["--config", str(cfgp)]
        self._pending_pool = str(Path(wd).resolve()) if idx == 0 and not self.report.get() else None

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
                out = str(Path(raw).parent / (Path(raw).name + '-切片'))
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
                "scene_detect": self.scene_on.get(),
                "scene_threshold": self.scene_th.get(),
                "max_per_scene": self.per_scene.get(),
                "boundary_margin": self.margin.get(),
            }
            return cmd, cfg, out

        d = self.c_dir.get().strip() or self.p_out.get().strip()
        if not d or not Path(d).is_dir():
            raise ValueError("请选择工作目录")
        from batch_cut import AUDIO_EXT, VIDEO_EXT, scan, resolve_bgm_directory
        if not any(scan(Path(d) / sub, VIDEO_EXT) for sub in ('clips', 'hooks', 'review')):
            raise ValueError("素材池为空，请先跑①切片入池")
        bgm_dir = resolve_bgm_directory(d, self.c_bgm.get()) if self.bgm_enabled.get() and self.c_bgm.get().strip() else None
        if bgm_dir is not None and not scan(bgm_dir, AUDIO_EXT):
            raise ValueError(f"音乐目录中没有可用音乐：{bgm_dir}\n"
                             "请点击“选择音乐文件夹”，选择含 MP3/M4A/WAV/AAC/FLAC 的目录。")
        if not CUT.is_file():
            raise ValueError(f"找不到 {CUT.name},请和本程序放在同一目录")
        w, h = (1080, 1920) if self.aspect.get() == "v" else (1920, 1080)
        sfx = dict(sfx_enabled=self.sfx_enabled.get(), sfx_path=self.sfx_path.get().strip(),
                   sfx_volume=self.sfx_volume.get() / 100, sfx_gap=self.sfx_gap.get())
        if sfx['sfx_enabled']:
            from flesh_sfx import audio_files, validate_settings, model_directory
            audio_files(sfx['sfx_path'])
            validate_settings(sfx)
            if not (model_directory() / 'vision.onnx').is_file():
                raise ValueError('缺少果肉识别模型，请保留程序旁的 models 文件夹')
        cfg = {
            **sfx,
            "batch_caption_enabled": self.batch_caption_enabled.get(),
            "batch_caption_text": self.batch_caption_text,
            "batch_caption_shuffle": self.batch_caption_shuffle.get(),
            "font_path": self.caption_font.get(),
            "caption": [v.get() for v in self.cap],
            "bgm_dir": str(bgm_dir) if bgm_dir else '',
            "bgm_enabled": self.bgm_enabled.get(),
            "width": w, "height": h,
            "shot_sec": [self.shot_min.get(), self.shot_max.get()],
            "total_sec": [self.tot_min.get(), self.tot_max.get()],
        }
        from caption_pool import plan_captions
        plan_captions(cfg, self.n.get())
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
                    self._sync_completed_pool(val)
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
