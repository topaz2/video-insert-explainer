"""Text drawing for 1920x1080 transparent overlays (Pillow; works where ffmpeg has no drawtext/subtitles).

Positions mean the ink, not the font origin: `left` / `top` are the left / top edges of the drawn glyphs,
so measured coordinates of burned-in text can be copied straight in.
"""

from PIL import Image, ImageDraw

from common import H, W

MAX_CHARS = 28


def canvas():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def draw_runs(img, runs, left, top, f, stroke=0, ref_text=None):
    """Draw [(text, fill, stroke_fill), ...] on one line with the ink's left/top edge at (left, top).
    ref_text: take the top from that text's ink instead, so lines of different glyphs share a baseline."""
    d = ImageDraw.Draw(img)
    whole = "".join(r[0] for r in runs)
    x = left - f.getbbox(whole)[0]
    y = top - f.getbbox(ref_text or whole)[1]
    for text, fill, stroke_fill in runs:
        d.text((x, y), text, font=f, fill=fill, stroke_width=stroke if stroke_fill else 0, stroke_fill=stroke_fill)
        x += f.getlength(text)
    return img


def run_width(text, f):
    b = f.getbbox(text)
    return b[2] - b[0]


def wrap(text, max_chars=MAX_CHARS):
    """Break only after 、 with the fewest lines and, among those, the most even lengths; hard-cut if needed."""
    if len(text) <= max_chars:
        return [text]
    cuts = sorted({i + 1 for i, ch in enumerate(text) if ch in "、，,"} | {len(text)})
    best, prev = {0: (0, 0)}, {}
    for j in cuts:
        for i in sorted(best):
            if i < j and j - i <= max_chars:
                cand = (best[i][0] + 1, max(best[i][1], j - i))
                if j not in best or cand < best[j]:
                    best[j], prev[j] = cand, i
    if len(text) not in best:
        head = max((c for c in cuts if c <= max_chars), default=max_chars)
        return [text[:head]] + wrap(text[head:], max_chars)
    lines, j = [], len(text)
    while j:
        lines.append(text[prev[j]: j])
        j = prev[j]
    return lines[::-1]


def telop(lines, f, stroke, fill=(255, 255, 255, 255), stroke_fill=(0, 0, 0, 255), center_x=W / 2,
          top=None, bottom=None, line_gap=1.25, box=None):
    """Centered multi-line telop. Give top (ink top of line 1) or bottom (bottom of the box, or of the ink).
    box = dict(fill=(r, g, b, a), radius=px, pad=px)."""
    step = round(f.size * line_gap)
    widths = [run_width(ln, f) for ln in lines]
    asc = f.getbbox("あ")
    ink_h = (asc[3] - asc[1]) + step * (len(lines) - 1)
    pad = box["pad"] if box else 0
    if top is None:
        top = bottom - pad - ink_h
    img = canvas()
    if box:
        bw = max(widths) + 2 * pad
        x0 = center_x - bw / 2
        ImageDraw.Draw(img).rounded_rectangle((x0, top - pad, x0 + bw, top + ink_h + pad), box["radius"], fill=box["fill"])
    for i, ln in enumerate(lines):
        draw_runs(img, [(ln, fill, stroke_fill)], center_x - widths[i] / 2, top + i * step, f, stroke, ref_text="あ")
    return img
