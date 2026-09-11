"""Render Chinese text and system color emoji as a transparent caption layer."""
import os
from pathlib import Path
import regex
from PIL import Image, ImageDraw, ImageFont


def render_caption(lines, width, height, size, font_path, color, output):
    emoji_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/seguiemj.ttf'
    clusters = [regex.findall(r'\X', line) for line in lines]
    has_emoji = lambda text: bool(regex.search(r'\p{Extended_Pictographic}|\p{Regional_Indicator}|\u20e3', text))
    if any(has_emoji(c) for row in clusters for c in row) and not emoji_path.exists():
        raise ValueError('找不到系统彩色表情字体 Segoe UI Emoji，请安装该字体后重试。')
    portrait = height >= width
    size = max(1, round(size * (width / 1080 if portrait else height / 1080)))
    image = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(image)
    while True:
        normal = ImageFont.truetype(str(font_path), size)
        emoji = ImageFont.truetype(str(emoji_path), size) if emoji_path.exists() else normal
        rows = [[(c, emoji if has_emoji(c) else normal, has_emoji(c)) for c in row] for row in clusters]
        lengths = [sum(draw.textlength(c, font=f) for c, f, _ in row) for row in rows]
        if max(lengths, default=0) <= width * (0.82 if portrait else 0.48) or size == 1:
            break
        size -= 1
    center = width * (0.5 if portrait else 0.285)
    top = round(height * (0.032 if portrait else 0.045))
    border = max(1, round(size * .045))
    for index, (row, length) in enumerate(zip(rows, lengths)):
        x = center - length / 2
        baseline = top + size + index * (size + round(size * .28))
        for text, font, colored in row:
            draw.text((x, baseline), text, font=font, anchor='ls',
                      fill=color, embedded_color=colored,
                      stroke_width=0 if colored else border, stroke_fill=(0, 0, 0, 217))
            x += draw.textlength(text, font=font)
    image.save(output)
    return output
