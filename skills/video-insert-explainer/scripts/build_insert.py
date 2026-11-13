"""Render the insert part frame by frame with Pillow and pipe it to ffmpeg (video only).

usage: python3 build_insert.py <project.json> --preview 0.2,6.7,22.0   # PNGs of chosen insert times T
       python3 build_insert.py <project.json> --render <insert.mp4>

Everything comes from the resolved events JSON (config "events"; see events.example.template.json) and the
telops manifest (make_telops.py). Coordinates are 1080p screen pixels, except zoom targets, which are rects
in slide-image pixels. Sequence: blurred freeze frame -> small slide rises in -> expands to full view ->
pages / zooms / bounces / markers / blinks / badges -> shrinks back -> slides out -> white flash.
"""

import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from common import (FLASH_HALF, H, W, Project, back, back_with_overshoot, clamp01, ease_in, ease_in_out, ease_out,
                    ff, font, hexrgb, lerp, run)

PAD = 64  # white margin around each slide so zoom crops never leave the image
pop_in = back(1.70158)


def with_alpha(img, k):
    if k >= 1:
        return img
    out = img.copy()
    out.putalpha(out.getchannel("A").point(lambda v: round(v * k)))
    return out


def extract_frame(path, n, out):
    run([ff(), "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-vf",
         f"select=eq(n\\,{n}),scale=in_color_matrix=bt709:in_range=tv,format=rgb24",
         "-fps_mode", "passthrough", "-frames:v", "1", out])
    return Image.open(out).convert("RGB")


class Insert:
    def __init__(self, pj):
        self.pj, ev = pj, pj.events
        self.ev = ev
        work = pj.p(pj.get("work_dir", "work"))
        os.makedirs(work, exist_ok=True)
        bg = ev.get("background", {})
        self.bg_sharp = extract_frame(pj.base, pj.cut_frame - 1, os.path.join(work, "freeze.png"))
        blur = self.bg_sharp.filter(ImageFilter.GaussianBlur(bg.get("blur", 10)))
        self.bg_blur = ImageEnhance.Brightness(blur).enhance(bg.get("brightness", 0.7))
        self.bg_fade = bg.get("crossfade", 0.4)
        self.slides = {}
        for i, path in enumerate(pj.get("slides"), start=1):
            im = Image.open(pj.p(path)).convert("RGB")
            padded = Image.new("RGB", (im.width + 2 * PAD, im.height + 2 * PAD), "white")
            padded.paste(im, (PAD, PAD))
            self.slides[i] = (im, padded)
        sw, sh = self.slides[1][0].size
        self.sw, self.sh = sw, sh
        self.s = min(W / sw, H / sh)
        self.full_x, self.full_y = (W - sw * self.s) / 2, (H - sh * self.s) / 2
        self.full_rect = (-self.full_x / self.s, -self.full_y / self.s, (W - self.full_x) / self.s, (H - self.full_y) / self.s)
        k = ev.get("small_scale", 0.55)
        self.small = ((W - sw * self.s * k) / 2, (H - sh * self.s * k) / 2, sw * self.s * k)
        self.full = {i: self.view(i, self.full_rect) for i in self.slides}
        self.badges = {b["slide"]: self.badge(b["text"], b.get("color", "#1971C2"), b.get("top", 20)) for b in ev.get("badges", [])}
        self.notes = [(n, self.badge(n["text"], n.get("color", "#E8590C"), n.get("top", 80))) for n in ev.get("notes", [])]
        self.pips = [Image.open(pj.p(ij["pip"])).convert("RGBA") for ij in ev.get("interjections", [])]
        self.telops = json.load(open(pj.p(pj.get("work_dir", "work") + "/telops/manifest.json"), encoding="utf-8"))
        for r in self.telops:
            img = Image.open(r["png"]).convert("RGBA")
            box = img.getchannel("A").getbbox()
            r["img"], r["box"] = img.crop(box), box
        self.zooms = {int(k): v for k, v in ev.get("zooms", {}).items()}
        self.turn_len, self.zoom_len = ev.get("turn_len", 0.4), ev.get("zoom_len", 0.6)
        self.rise = back_with_overshoot(ev["entry"].get("overshoot", 0.06))
        self.n_frames = pj.insert_frames
        self.flash_start = self.n_frames / pj.fps - FLASH_HALF
        self.last_slide = ev["pages"][-1][0]
        self.cache = {}

    def view(self, i, rect):
        _, padded = self.slides[i]
        x0, y0, x1, y1 = rect
        return padded.resize((W, H), Image.BICUBIC, box=(x0 + PAD, y0 + PAD, x1 + PAD, y1 + PAD))

    def badge(self, text, color, top, right=1880):
        """White rounded tag with a faint shadow so it does not melt into white slide areas."""
        f = font(self.pj, 6, 28)
        x0 = right - (f.getlength(text) + 40)
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((x0, top + 2, right, top + 50), 24, fill=(0, 0, 0, 64))
        img = sh.filter(ImageFilter.GaussianBlur(6))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x0, top, right, top + 48), 24, fill=(255, 255, 255, 255))
        bb = f.getbbox(text)
        d.text((x0 + 20 - bb[0], top + (48 - (bb[3] - bb[1])) / 2 - bb[1]), text, font=f, fill=hexrgb(color))
        return img

    def small_at(self, i, left, top, width):
        key = (i, round(left, 1), round(top, 1), round(width, 1))
        if key in self.cache:
            return self.cache[key]
        im, _ = self.slides[i]
        h = width * self.sh / self.sw
        c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle((left, top + 12, left + width, top + 12 + h), fill=(0, 0, 0, 128))
        c.alpha_composite(sh.filter(ImageFilter.GaussianBlur(24)))
        c.paste(im.resize((max(1, round(width)), max(1, round(h))), Image.BICUBIC), (round(left), round(top)))
        if (left, top, width) == self.small:
            self.cache[key] = c
        return c

    def zoom_rect(self, slide, t):
        rect = self.full_rect
        for t0, target in self.zooms.get(slide, []):
            if t < t0:
                break
            to = self.full_rect if target is None else (target[0], target[1], target[0] + target[2], target[1] + target[3])
            rect = tuple(lerp(a, b, ease_in_out((t - t0) / self.zoom_len)) for a, b in zip(rect, to))
        return rect

    def zoomed_spans(self, slide):
        spans, start = [], None
        for t0, target in self.zooms.get(slide, []):
            if target is not None and start is None:
                start = t0
            elif target is None and start is not None:
                spans.append((start, t0 + self.zoom_len))
                start = None
        return spans

    def badge_alpha(self, slide, t, fade=0.2):
        """Tags sit in full-view coordinates, so they fade out while the slide is zoomed in."""
        k = 1.0
        for s, e in self.zoomed_spans(slide):
            if s <= t < e:
                k = min(k, 1 - clamp01((t - s) / fade))
            elif e <= t < e + fade:
                k = min(k, clamp01((t - e) / fade))
        return k

    def page(self, slide, t):
        ev = self.ev
        rect = self.zoom_rect(slide, t)
        img = (self.full[slide] if rect == self.full_rect else self.view(slide, rect)).copy().convert("RGBA")
        for s, t0, (x, y, w, h) in ev.get("bounces", []):
            if s == slide and t0 <= t < t0 + 0.2:
                r = (t - t0) / 0.1 if t < t0 + 0.1 else (t0 + 0.2 - t) / 0.1
                k = 1 + 0.05 * ease_in_out(r)
                card = img.crop((x, y, x + w, y + h)).resize((round(w * k), round(h * k)), Image.BICUBIC)
                img.paste(card, (round(x + w / 2 - w * k / 2), round(y + h / 2 - h * k / 2)))
        mc = ev.get("marker", {})
        for s, t0, t1, (x, y, w, h) in ev.get("markers", []):
            if s == slide and t0 <= t < t1:
                mw = w * clamp01((t - t0) / mc.get("grow", 0.4))
                if mw >= 1:
                    m = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    ImageDraw.Draw(m).rectangle((x, y, x + mw, y + h), fill=hexrgb(mc.get("color", "#FFE14D"), round(255 * mc.get("alpha", 0.45))))
                    img.alpha_composite(m)
        bc = ev.get("blink", {})
        for s, t0, (x, y, w, h) in ev.get("blinks", []):
            if s == slide and (t0 <= t < t0 + 0.15 or t0 + 0.3 <= t < t0 + 0.45):
                g = bc.get("grow", 12)  # drawn outside the target so it surrounds an existing red frame instead of merging with it
                ImageDraw.Draw(img).rectangle((x - g, y - g, x + w + g, y + h + g), outline=hexrgb(bc.get("color", "#E53935")), width=bc.get("width", 12))
        if slide in self.badges:
            k = self.badge_alpha(slide, t)
            if k > 0:
                img.alpha_composite(with_alpha(self.badges[slide], k))
        for n, im in self.notes:
            if n["slide"] == slide and n["start"] <= t < n["end"]:
                f = n.get("fade", 0.2)
                k = min(clamp01((t - n["start"]) / f), clamp01((n["end"] - t) / f), self.badge_alpha(slide, t))
                if k > 0:
                    img.alpha_composite(with_alpha(im, k))
        return img

    def frame(self, t):
        ev, (sx, sy, sw) = self.ev, self.small
        full_w = self.sw * self.s
        img = (Image.blend(self.bg_sharp, self.bg_blur, t / self.bg_fade) if t < self.bg_fade else self.bg_blur).convert("RGBA")
        e0, e1 = ev["entry"]["expand"]
        s0, s1 = ev["shrink"]
        x0, x1 = ev["exit"]
        if t < e0:
            img.alpha_composite(self.small_at(1, sx, lerp(H, sy, self.rise(t / ev["entry"].get("rise_end", 0.5))), sw))
        elif t < e1:
            r = ease_out((t - e0) / (e1 - e0))
            img.alpha_composite(self.small_at(1, lerp(sx, self.full_x, r), lerp(sy, self.full_y, r), lerp(sw, full_w, r)))
        elif t < s0:
            img = Image.new("RGBA", (W, H), "white")
            turn = next(((t0, a, b) for t0, a, b in ev.get("turns", []) if t0 <= t < t0 + self.turn_len), None)
            if turn:
                t0, a, b = turn
                shift = round(W * ease_in_out((t - t0) / self.turn_len))
                if shift < W:  # alpha_composite takes no negative offsets, so crop the outgoing page instead
                    img.alpha_composite(self.page(a, t), (0, 0), (shift, 0))
                if shift > 0:
                    img.alpha_composite(self.page(b, t), (W - shift, 0))
            else:
                slide = next((s for s, p0, p1 in ev["pages"] if p0 <= t < p1), ev["pages"][-1][0])
                img = self.page(slide, t)
        elif t < s1:
            r = ease_in_out((t - s0) / (s1 - s0))
            img.alpha_composite(self.small_at(self.last_slide, lerp(self.full_x, sx, r), lerp(self.full_y, sy, r), lerp(full_w, sw, r)))
            k = 1 - clamp01((t - s0) / 0.2)
            if k > 0 and self.last_slide in self.badges:
                img.alpha_composite(with_alpha(self.badges[self.last_slide], k))
        elif t < x0:
            img.alpha_composite(self.small_at(self.last_slide, sx, sy, sw))
        elif t < x1:
            img.alpha_composite(self.small_at(self.last_slide, lerp(sx, W, ease_in((t - x0) / (x1 - x0))), sy, sw))

        px, py = ev.get("pip_pos", [1500, 620])
        for ij, pip in zip(ev.get("interjections", []), self.pips):
            t0 = ij["t"] - 0.1  # face inset: from 0.1 s before the voice for 0.9 s, pop in 0.15 s, fade the last 0.15 s
            if t0 <= t < t0 + 0.9:
                k = pop_in((t - t0) / 0.15)
                pw, ph = max(1, round(pip.width * k)), max(1, round(pip.height * k))
                p = with_alpha(pip.resize((pw, ph), Image.BICUBIC), clamp01((t0 + 0.9 - t) / 0.15))
                img.alpha_composite(p, (round(px + pip.width / 2 - pw / 2), round(py + pip.height / 2 - ph / 2)))

        for r in self.telops:
            if r["start"] <= t < r["end"]:
                k = 1.0
                if r["fade_in"]:
                    k = min(k, clamp01((t - r["start"]) / r["fade_in"]))
                if r["fade_out"]:
                    k = min(k, clamp01((r["end"] - t) / r["fade_out"]))
                if k > 0:
                    img.alpha_composite(with_alpha(r["img"], k), r["box"][:2])

        if t >= self.flash_start:  # the fall of the flash happens on the source side (assemble.py)
            img = Image.blend(img.convert("RGB"), Image.new("RGB", (W, H), "white"), clamp01((t - self.flash_start) / FLASH_HALF))
        return img.convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--preview", default="")
    ap.add_argument("--outdir", default="")
    ap.add_argument("--render", default="")
    a = ap.parse_args()
    pj = Project(a.project)
    ins = Insert(pj)
    if a.preview:
        outdir = a.outdir or pj.p(pj.get("work_dir", "work") + "/preview_frames")
        os.makedirs(outdir, exist_ok=True)
        for tok in a.preview.split(","):
            k = round(float(tok) * pj.fps)
            path = os.path.join(outdir, f"T{k / pj.fps:07.3f}.png")
            ins.frame(k / pj.fps).save(path)
            print(path)
    if a.render:
        cmd = [ff(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
               "-r", str(pj.fps), "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
               "-c:v", "libx264", "-crf", "12", "-preset", "medium",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", a.render]
        import subprocess
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for k in range(ins.n_frames):
            proc.stdin.write(ins.frame(k / pj.fps).tobytes())
            if k % 300 == 0:
                print(f"frame {k}/{ins.n_frames}", flush=True)
        proc.stdin.close()
        sys.exit(proc.wait())


if __name__ == "__main__":
    main()
