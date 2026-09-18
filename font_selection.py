"""System/custom caption fonts, shared by preview and final rendering."""
import os
from pathlib import Path
from PIL import ImageFont


def resolve_font(selected='', fallback=None):
    path = str(selected).strip() or fallback
    if not path or not Path(path).is_file():
        raise ValueError('找不到字幕字体，请重新选择字体文件')
    try:
        ImageFont.truetype(str(path), 32)
    except (OSError, ValueError) as exc:
        raise ValueError('无法读取该字体，请选择有效的 TTF、OTF 或 TTC 文件') from exc
    return str(Path(path).resolve())


def installed_fonts():
    folders = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts',
               Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Microsoft/Windows/Fonts']
    aliases = {'msyhbd.ttc': '微软雅黑 · 粗体', 'msyh.ttc': '微软雅黑',
               'simhei.ttf': '黑体', 'simsun.ttc': '宋体', 'simkai.ttf': '楷体',
               'simfang.ttf': '仿宋', 'msyhl.ttc': '微软雅黑 · 细体',
               'Deng.ttf': '等线', 'Dengb.ttf': '等线 · 粗体', 'Dengl.ttf': '等线 · 细体'}
    result = {}
    for folder in folders:
        if not folder.is_dir(): continue
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in ('.ttf', '.otf', '.ttc'): continue
            try:
                font = ImageFont.truetype(str(path), 24)
                # Filter obvious Latin/symbol fonts whose Chinese characters are both .notdef.
                a,b=font.getmask('果'),font.getmask('肉')
                if not a.getbbox() or (a.size == b.size and bytes(a) == bytes(b)): continue
                name=aliases.get(path.name, ' · '.join(font.getname()))
                label=f'{name}（{path.name}）'
                if label in result: label=f'{label} · 用户字体'
                result[label]=str(path)
            except (OSError, ValueError): continue
    return result
