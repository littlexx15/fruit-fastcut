# 水果快切混剪工具 · Fruit FastCut

Windows 桌面视频混剪工具：原片切片、人脸检测裁切、横竖屏输出、固定三行文案和批量选镜。

## 软件界面

切片入池：

![切片入池界面](docs/images/gui-prep.png)

批量出片：

![批量出片界面](docs/images/gui-export.png)

## 成片效果示例

### 新示例：云南爱媛果冻橙

约 37 秒，在线播放版 540×960，完整声音和时长：

https://github.com/user-attachments/assets/8a85750a-00ba-43a7-8fdd-a5cf7400357c

[下载原始清晰版（约 24 MB）](docs/examples/orange-finished.mp4)

### 板栗红薯

板栗红薯成片，约 39 秒。点击下方播放器即可在线观看，无需先下载。在线播放版为 540×960，保留完整时长和声音。

https://github.com/user-attachments/assets/6b04cb87-c370-4231-a442-0880abd5b886

[下载原始清晰版（1080×1920，MP4，约 28 MB）](docs/examples/sweet-potato-finished.mp4)

示例由项目维护者提供，作为效果展示；不包含原始素材池。

## Windows 运行包

从 GitHub Releases 下载 `FruitFastCut-windows-x64.zip`，**完整解压**后打开 `FruitFastCut.exe`。无需安装 Python。请保留旁边的 `_internal` 文件夹。

运行前需要安装 FFmpeg，并让 `ffmpeg`、`ffprobe` 能在命令行运行。Windows 可使用 `winget install Gyan.FFmpeg`，安装后重新启动程序。程序运行包不包含 FFmpeg。

## 使用方法

1. 选择原始视频目录，工作目录自动填写为同级的“原目录名-切片”，也可手动修改。
2. 点击开始，全部切片统一保存到 `clips/`。成功后工作目录自动同步到批量出片页。
3. 选择背景音乐文件夹，填写文案（支持直接粘贴 🍊 😋 ❤️）、条数、时长和画幅，然后开始。
4. 成片、封面和镜头清单保存在工作目录的 `out/`。

旧 `hooks/`、`clips/`、`review/` 合并参与选镜，不再按文件名或暖色比例打标。仅出检测报告或任务失败时，不切换出片目录。

## 画面处理

- 竖屏 1080×1920；横屏 1920×1080。按每段素材的实际方向处理：同方向不旋转，方向相反才顺时针旋转 90°；文字保持正向。
- 所有素材使用**等比例缩放铺满**，不单向拉伸、不改变物体形状。比例不一致时居中裁掉超出画幅的部分：4:3→16:9 裁上下；3:4→9:16 裁左右。4:3→竖屏先旋转成 3:4，再等比放大并裁左右；3:4→横屏同理。方形素材直接等比缩放后裁溢出部分。
- 稳定的原片纯黑边经多个时间点确认后去除，再等比缩放填满。整段黑场不会被误当作黑边裁掉；检测结果缓存到 `_geometry_cache.json`，素材更新后自动重算。
- 识别手机视频的旋转元数据，避免重复旋转。人脸裁切导致宽高关系改变时，仍沿用裁切前的横竖方向。
- 检出人脸后，仅用当前切片内相邻采样的确认结果裁去眼线上方，再等比缩放并裁掉溢出部分以铺满画幅，不补黑边。
- 使用 YuNet 模型，默认每秒采样 5 帧、置信度 0.9。检测并不保证零误检、零漏检，重要素材请查看报告并预览。
- 默认字号 58；竖版顶部居中，横版左上区域各行居中，紧凑行距；长文案自动缩小。
- 中文和彩色 emoji 合成为透明字幕层，直接复制到文案框即可。Windows 使用系统 Segoe UI Emoji 字体，具体表情支持和外观随系统字体版本变化。

## 选镜与音乐

- 整批共享素材轮次：优先随机使用本轮未用切片，全部用完后再进入下一轮。重新点击开始会开启新批次。
- 同源镜头尽量错开，但不会因此提前复用；素材少于一条所需时，用完一轮后可在同一条中复用。
- 轮次按切片路径统计，未进行跨文件的视觉相似度识别；不同文件若本身画面相同，仍可能看起来重复。
- `manifest.json` 的 `timeline` 记录切片路径、原片来源、起点和时长。
- 独立音乐目录支持 MP3、M4A、WAV、AAC、FLAC，留空使用工作目录的 `bgm/`。
- 每条随机一首，每轮用完全部歌曲后再随机，多首时相邻不重复。每首固定从 0 秒播放，短音乐循环到成片结束。

## 从源码运行

推荐 Python 3.12（含 Tkinter），并安装 FFmpeg。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python launcher.py
```

命令行方式：

```powershell
python prep_clips.py --src "原片目录" --out "新工作目录"
python batch_cut.py --dir "工作目录" --n 20 --config "config.json"
python -m unittest discover -s tests
```

配置 JSON 可覆盖 `prep_clips.py` 中的 `CFG` 或 `batch_cut.py` 中的 `CONFIG`。原素材池已裁掉的内容无法恢复；旧版素材池需要从原片重新构建。程序不上传视频、图片或音乐到网络。

## 构建 Windows 包

在 Windows、Python 3.12 环境运行 `build_windows.ps1`。产物位于 `dist/FruitFastCut/`，压缩包位于 `dist/`。FFmpeg 单独安装，不随包分发。

第三方模型来源与许可证见 `THIRD_PARTY_NOTICES.md` 和 `licenses/`。本仓库仅包含明确选定的展示成片，不包含原始素材池、单独音乐文件或本地验证输出。
