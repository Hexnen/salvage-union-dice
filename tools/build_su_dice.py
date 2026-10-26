#!/usr/bin/env python3
"""Build the Salvage Union "Scrapyard" dice set.

Thin wrapper over the foundry-vtt-module skill pipeline (dice_common + build_set + fit_face_to_uv):
ONE image2 call per die, art baked from the exact DSN face template, Typo Draft numerals baked into
the mockup in rust-orange, and BOTH source images (the Crawler #279 emblem + the Salvage Union cover)
passed to image2 as inspiration alongside the mockup. Full (opaque) faces — the weathered look is baked
into each face image.

    python build_su_dice.py --dice d6 --prep                 # free: montage preview only
    python build_su_dice.py --dice d6                         # one die (becomes the style anchor)
    python build_su_dice.py --dice d4,d8,d10,d12,d20          # the rest (reuses d6 look + both refs)
"""
import argparse
import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SKILL = Path("C:/Users/santa/.claude/skills/foundry-vtt-module/scripts")
sys.path.insert(0, str(SKILL))

import dice_common as dc          # noqa: E402
import fit_face_to_uv as fit      # noqa: E402
import build_set as bs            # noqa: E402

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
FONT = str(MODULE / "fonts" / "TypoDraftDemo.otf")
ART = MODULE / "art"
CRAWLER = ART / "crawler.png"     # the orange Crawler #279 badge
COVER = ART / "cover.png"         # the light-blue grunge Salvage Union cover
OUT = MODULE / "textures"
ENV = MODULE / "image2api.env"

# Weathered sky-blue base painted into each mockup face (matches the cover background). image2 then
# distresses it. NOT a crop of the cover (its centre holds the SALVAGE UNION title which would bake
# stray lettering onto every face).
FILL = (140, 199, 214, 255)
# Rust-orange numeral baked into the mockup so image2 carves/keeps the exact glyph + colour.
ORANGE_INK = (199, 74, 38, 255)


# --- numerals: Typo Draft Demo lacks a usable "5" (its glyph is a "Personal Use Only" watermark
# badge), so we hand-build a "5" from the font's own strokes (uppercase "S" + a top bar and left
# spine sourced from the rotated "1" stem) — same weight, scratch texture and draft ticks. image2 is
# then told to harmonise it into one consistent numeral style with the rest. -----------------------
_GLYPH_CACHE = {}


def _glyph(ch, fill, px=440):
    key = (ch, fill)
    if key not in _GLYPH_CACHE:
        f = ImageFont.truetype(FONT, px)
        im = Image.new("RGBA", (px * 2, px * 2), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((px, px), ch, font=f, fill=fill, anchor="mm")
        _GLYPH_CACHE[key] = im.crop(im.getbbox())
    return _GLYPH_CACHE[key]


def make_five(target_h, fill):
    """A "5" assembled from the font's own glyphs: S body + top bar + left spine (from "1")."""
    S = _glyph("S", fill)
    one = _glyph("1", fill)
    s = target_h / S.height
    S = S.resize((max(1, int(S.width * s)), int(target_h)), Image.LANCZOS)
    W, H = S.size
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(S, (0, 0))
    bar = one.rotate(90, expand=True).resize((int(W * 0.92), int(H * 0.17)), Image.LANCZOS)
    vert = one.resize((int(W * 0.20), int(H * 0.46)), Image.LANCZOS)
    canvas.alpha_composite(vert, (int(W * 0.02), int(H * 0.07)))
    canvas.alpha_composite(bar, (int(W * 0.01), 0))
    return canvas


def render_number(text, target_h, fill):
    """Render a (possibly multi-digit) number at a uniform per-digit height, substituting our
    hand-built glyph for every "5". Each digit is height `target_h`; concatenated with light kerning."""
    parts = [make_five(target_h, fill) if ch == "5" else dc.plain_numeral(FONT, ch, target_h, fill=fill)
             for ch in text]
    gap = max(1, int(target_h * 0.06))
    W = sum(p.width for p in parts) + gap * (len(parts) - 1)
    H = max(p.height for p in parts)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x = 0
    for p in parts:
        out.alpha_composite(p, (x, (H - p.height) // 2))
        x += p.width + gap
    return out.crop(out.getbbox())


def build_input_su(die, shapes, patch):
    """Montage with the weathered-blue face fill, the dark outline, and orange Typo Draft numerals
    (custom "5"), each sized to a uniform height and fit clear of the edges (dc.fit_numeral)."""
    cols, rows = dc.grid_dims(die)
    img = Image.new("RGBA", (cols * bs.CELL, rows * bs.CELL), bs.GREEN)
    poly = dc.polygon_for(die, shapes)
    nums = dc.numbers_for(die)
    target_h = bs.CELL * bs.NUMERAL_H
    # The downward nudge is a WHOLE-DIE decision, not per face: apply it only to dice that actually
    # contain two-digit values (d12, d20) — uniformly across all their faces, so each such die reads
    # consistently. Purely single-digit dice (d4/d6/d8/d10, incl. d10's 0-9) keep centred numerals.
    nudge = 0.12 if any(len(n) > 1 for n in nums) else 0.0
    for i in range(dc.DICE[die]["faces"]):
        x0, y0 = (i % cols) * bs.CELL, (i // cols) * bs.CELL
        cell = Image.new("RGBA", (bs.CELL, bs.CELL), (0, 0, 0, 0))
        d = ImageDraw.Draw(cell)
        pts = dc.poly_px(poly, 0, 0, bs.CELL)
        m = Image.new("L", (bs.CELL, bs.CELL), 0)
        ImageDraw.Draw(m).polygon(pts, fill=255)
        cell.paste(patch, (0, 0), m)
        d.polygon(pts, outline=(20, 20, 24, 255), width=5)
        if dc.DICE[die]["kind"] == "d4":
            _, _, r = dc.incenter(pts)
            dc.draw_d4_triplet(cell, pts, dc.D4_TRIPLETS[i], FONT, carved=False,
                               target_h=r * 0.95, fill=ORANGE_INK)
        else:
            dc.fit_numeral(cell, render_number(nums[i], target_h, ORANGE_INK), pts, dy_frac=nudge)
        img.alpha_composite(cell, (x0, y0))
    return img

# image2 only does the right thing if it KNOWS what each input image is. The edits call sends, in order:
#   IMAGE 1 = the layout mockup (this die's montage)   IMAGE 2 = the cover (palette/texture ref)
#   IMAGE 3 = the Crawler #279 emblem (ink/stencil ref)  IMAGE 4 = a finished die from the set (lock), if any
# build_prompt spells out each image's ROLE, the per-die face shape and count, the d4 3-numeral layout,
# the restyle task, and hard rules against hallucinating/reshaping faces.
SHAPE = {"d4": "triangle", "d6": "square", "d8": "triangle",
         "d10": "kite (a 4-cornered diamond, point up)", "d12": "pentagon", "d20": "triangle"}


def build_prompt(die, has_anchor):
    n = dc.DICE[die]["faces"]
    shape = SHAPE[die]
    p = (f"You are given several images. IMAGE 1 is a LAYOUT MOCKUP on a flat pure-green background: a "
         f"grid of EXACTLY {n} die faces, each an outlined {shape} containing a rust-ORANGE numeral. "
         f"IMAGE 1 defines the layout you MUST reproduce exactly — the same {n} faces, each in the same "
         f"position, at the same size, with the same {shape} silhouette, showing the same numeral. ")
    if die == "d4":
        p += ("IMPORTANT for this die: each triangular face carries THREE separate small numerals — one "
              "tucked into each corner and rotated to point toward that corner. Keep ALL THREE numerals "
              "on every face exactly where IMAGE 1 places them; never merge them into one big numeral and "
              "never drop any. ")
    p += ("The remaining images are STYLE REFERENCES ONLY — copy their LOOK, never their layout. IMAGE 2 "
          "is the SALVAGE UNION cover: a pale, scuffed, heavily distressed sky-blue/teal grunge surface "
          "with bold rust-orange ink — match this exact palette and worn paint/print texture. IMAGE 3 is "
          "the round CRAWLER #279 emblem — match its rust-orange screen-printed, ink-eroded stencil "
          "quality and heavy weathering. ")
    if has_anchor:
        p += ("IMAGE 4 is a die already finished for this set — match it EXACTLY (same weathered surface, "
              "same frame design, same numeral treatment) so this new die clearly belongs to the same set. ")
    p += (f"YOUR TASK: repaint IMAGE 1. Restyle each outlined {shape} face into a battered Salvage-Union "
          "crate marking: a pale weathered sky-blue painted-metal surface with HEAVY distress (scuffs, "
          "scratches, chipped paint, rust speckles, grime, rough stencil grain); plus a bold dark stencil "
          f"frame just inside the face edge that FOLLOWS THE FACE'S EXACT {shape.upper()} OUTLINE — never "
          "squared off, rounded or reshaped — using ONE identical frame design on every face. Keep every "
          "numeral EXACTLY as in IMAGE 1 (same digits, shape, position and rust-orange colour); only give "
          "it a clean, consistent stamped-stencil finish. Draw every '5' as ONE clean solid numeral in "
          "the same style and weight as the other digits (no seams or doubled strokes). ")
    p += (f"STRICT RULES: reproduce IMAGE 1's grid EXACTLY — the same {n} faces, same {shape} shapes, same "
          "positions, same numerals. Do NOT add, invent, duplicate, move or remove any face, tile, row, "
          "numeral or decoration. Every pixel that is NOT one of IMAGE 1's outlined faces MUST be pure "
          "flat saturated chroma-green (RGB 0,255,0): clean green screen, no gradient, no shadow, no extra "
          "tiles. Nothing may cross or touch a face outline. No extra text, no logo, no watermark.")
    return p

# d6 face polygon (cell-local) from dsn-face-uv.json — the inset rect the cube samples.
D6_RECT = (0.013, 0.012, 0.990, 0.989)
SIZE = 512


def slice_faces(die, atlas_path):
    """d6: fit each face into the inset RECT with NO rotation (the generic kite-corner warp rotates a
    square 45deg — see the dice-d6-rectfit-not-warp note). Other dice: warp to the UV polygon.

    d6 faces are FULL OPAQUE squares, so we do NOT chroma-key them to alpha: keying eats dark frame
    pixels that blend into the green edge, leaving transparent holes that read as a broken/cut corner
    on the die. Instead we despill the green tint, crop away the green margin by the non-green bbox,
    and keep the tile fully opaque (frame gaps stay blue, no holes)."""
    if die != "d6":
        fit.warp_atlas(die, atlas_path, OUT, size=SIZE, bumps=True)
        return
    import numpy as np
    atlas = Image.open(atlas_path).convert("RGB")
    cols, rows = dc.grid_dims(die)
    cw, ch = atlas.width // cols, atlas.height // rows
    x0, y0, x1, y1 = D6_RECT
    tx0, ty0 = round(x0 * SIZE), round(y0 * SIZE)
    tw, th = round((x1 - x0) * SIZE), round((y1 - y0) * SIZE)
    for i in range(dc.DICE[die]["faces"]):
        c, r = i % cols, i // cols
        a = np.asarray(atlas.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch))).astype(np.int16)
        R, G, B = a[..., 0], a[..., 1], a[..., 2]
        is_green = (G >= 90) & ((G - R) >= 35) & ((G - B) >= 35)
        cap = np.maximum(R, B)                       # despill: pull green down to the next channel
        rgb = np.dstack([R, np.where(G > cap, cap, G), B]).astype(np.uint8)
        ys, xs = np.where(~is_green)                 # tile = everything that ISN'T the green screen
        if len(xs):
            bx0, by0, bx1, by1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        else:
            bx0, by0, bx1, by1 = 0, 0, cw, ch
        tile = Image.fromarray(rgb[by0:by1, bx0:bx1]).resize((tw, th), Image.LANCZOS)
        face = Image.new("RGB", (SIZE, SIZE), FILL[:3])   # opaque; sky-blue fills the thin rect margin
        face.paste(tile, (tx0, ty0))
        face.save(OUT / f"{die}f{i + 1}.webp", "WEBP", quality=92, method=6)
        face.convert("L").save(OUT / f"{die}f{i + 1}-bump.webp", "WEBP", quality=90, method=6)
    print(f"  {die}: opaque rect-fit {dc.DICE[die]['faces']} faces (despill, no alpha holes)")


def process(die, prep, refs):
    shapes = dc.load_shapes()
    work = OUT / "_work"
    work.mkdir(parents=True, exist_ok=True)
    patch = Image.new("RGBA", (bs.CELL, bs.CELL), FILL)
    montage = build_input_su(die, shapes, patch)
    montage.save(work / f"{die}_input.webp", "WEBP", lossless=True)
    if prep:
        print(f"[{die}] PREP -> {work / (die + '_input.webp')} (no API)")
        return None, 0.0
    cols, rows = dc.grid_dims(die)
    key = dc.load_key(str(ENV))
    use_refs = list(refs)
    # Lock the set to the realised d6 look once it exists (becomes IMAGE 4 in the prompt).
    d6_out = work / "d6_out.webp"
    has_anchor = die != "d6" and d6_out.exists()
    if has_anchor:
        use_refs.append(Image.open(d6_out).convert("RGB"))
    prompt = build_prompt(die, has_anchor)
    print(f"[{die}] salvage full: one image2 call ({cols}x{rows}) [+{len(use_refs)} refs] ...")
    png, usage = dc.image2_edit(montage, prompt, key, bs.request_size(cols, rows),
                                "gpt-image-2", "medium", extra_refs=use_refs)
    cost = dc.usage_cost("gpt-image-2", usage)
    out_img = work / f"{die}_out.webp"
    Image.open(io.BytesIO(png)).convert("RGB").save(out_img, "WEBP", quality=95)
    slice_faces(die, out_img)
    print(f"  cost ${cost:.4f}")
    return die, cost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dice", default="d4,d6,d8,d10,d12,d20")
    ap.add_argument("--prep", action="store_true")
    a = ap.parse_args()
    dice = [d.strip() for d in a.dice.split(",") if d.strip()]
    OUT.mkdir(parents=True, exist_ok=True)

    refs = []
    if not a.prep:
        for p in (COVER, CRAWLER):            # both source images, as inspiration, every call
            if not p.exists():
                raise SystemExit(f"Missing source image: {p}\n"
                                 f"Drop the two images into {ART} as cover.png and crawler.png.")
            refs.append(Image.open(p).convert("RGB"))

    made, total = [], 0.0
    for d in dice:
        die, cost = process(d, a.prep, refs)
        if die:
            made.append(die)
            total += cost

    if a.prep:
        prev = bs.build_preview(OUT, dice, "input")
        print(f"\nPREP done (no API). Preview -> {prev}")
        return
    if made:
        prev = bs.build_preview(OUT, made, "faces")
        cost_path = OUT / "_cost.json"
        prev_total = 0.0
        if cost_path.exists():
            try:
                prev_total = json.loads(cost_path.read_text()).get("usd", 0.0)
            except Exception:
                prev_total = 0.0
        cost_path.write_text(json.dumps(
            {"usd": round(prev_total + total, 4), "this_run": round(total, 4),
             "model": "gpt-image-2", "dice": made}, indent=2))
        print(f"\nDone: {', '.join(made)} -> {OUT}")
        print(f"COST this run: ${total:.4f}   CUMULATIVE (salvage-union-dice): ${prev_total + total:.4f}")
        print(f"PREVIEW: {prev}")


if __name__ == "__main__":
    main()
