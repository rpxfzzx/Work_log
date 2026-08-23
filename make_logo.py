# -*- coding: utf-8 -*-
"""生成工作日志的标志性 Logo。

设计语言：靛蓝渐变圆角方块（沉稳专业）+ 白色日志文档三条记录线（工作日志）
+ 绿色圆形完成勾（已完成的标志）—— 整体意象为“把工作记录下来并一件件完成”。

输出（1024px 超采样绘制后缩小，保证边缘平滑）：
  logo.ico    多尺寸 Windows 图标（打包 exe 用）
  logo.png    256x256（展示/文档用）
  logo_64.png 64x64（程序窗口标题栏图标用）

重新生成：python make_logo.py
"""
import os

from PIL import Image, ImageDraw, ImageFilter

BASE = os.path.dirname(os.path.abspath(__file__))

# 品牌配色（与周报页眉徽标保持一致）
INDIGO_TOP = (63, 81, 181)      # #3F51B1
INDIGO_BOTTOM = (31, 78, 121)   # #1F4E79
GREEN = (76, 175, 80)           # #4CAF50
WHITE = (255, 255, 255)
LINE_GRAY = (176, 184, 205)
SHADOW = (0, 0, 0, 70)

S = 1024  # 超采样尺寸


def _gradient_square(size):
    img = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(size - 1, 1)
        c = tuple(int(a + (b - a) * t) for a, b in zip(INDIGO_TOP, INDIGO_BOTTOM))
        d.line([(0, y), (size, y)], fill=c)
    return img


def _paper_shadow(size):
    """白色文档下方的柔和投影。"""
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(shadow)
    d.rounded_rectangle([212, 266, 772, 830], radius=64, fill=SHADOW)
    return shadow.filter(ImageFilter.GaussianBlur(18))


def build_logo(size=S):
    img = _gradient_square(size)

    # 文档阴影 + 白色文档
    shadow = _paper_shadow(size)
    img.paste(shadow, (0, 0), shadow)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([190, 240, 750, 800], radius=64, fill=WHITE)

    # 文档上的三条记录线（第三条短一截，像未写完）
    for i, (x2, yy) in enumerate(((650, 380), (650, 475), (540, 570))):
        d.rounded_rectangle([270, yy, x2, yy + 28], radius=14, fill=LINE_GRAY)

    # 绿色完成圆勾，压在文档右下角
    d.ellipse([560, 596, 872, 908], fill=GREEN, outline=WHITE, width=16)
    d.line([(648, 752), (716, 820), (796, 656)], fill=WHITE, width=62, joint="curve")

    # 圆角背景裁剪（透明四角）
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=200, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main():
    img = build_logo(1024)
    logo256 = img.resize((256, 256), Image.LANCZOS)
    logo64 = img.resize((64, 64), Image.LANCZOS)
    logo256.save(os.path.join(BASE, "logo.png"))
    logo64.save(os.path.join(BASE, "logo_64.png"))
    logo256.save(
        os.path.join(BASE, "logo.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Logo generated:")
    print("  logo.ico   （多尺寸，打包 exe 用）")
    print("  logo.png   （256x256 展示）")
    print("  logo_64.png（64x64 窗口图标）")


if __name__ == "__main__":
    main()
