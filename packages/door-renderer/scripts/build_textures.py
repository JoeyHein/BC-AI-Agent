#!/usr/bin/env python3
"""Build seamless woodgrain tiles from finishes.json.

For each finish with type "woodgrain":

  1. If textureSource (or sources/<id>.jpg) exists, crop textureCrop,
     rotate textureRotate degrees, and make a seamless tile. That is a
     real catalogue texture.
  2. Otherwise recolour the walnut tile toward hex using grainContrast.
     That result is interim. Set textureStatus to "interim".

textureRotate is how a source photo is turned so grain matches installed
doors. Kanata and Craft catalogue photos, and installed chestnut doors,
run grain horizontally. A section photo stood on end needs 90 degrees.

poreEmboss, when set, bakes a light directional shade from the tile's own
luminance so pores keep a little depth at preview size. The shade is
wrapped so the tile stays seamless.

Run from the repo root:

    python packages/door-renderer/scripts/build_textures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "finishes.json"
TEXTURES = ROOT / "textures"
SOURCES = ROOT / "sources"
# Never enlarge a crop. Cap only if a side is extreme; tiles should stay >=1024 on the long side.
MAX_TILE = 1600


def load_manifest():
    return json.loads(MANIFEST.read_text())


def hex_to_rgb(value: str) -> np.ndarray:
    value = value.lstrip("#")
    return np.array([int(value[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def drop_in_path(finish_id: str) -> Path:
    return SOURCES / f"{finish_id.lower().replace('_', '-')}.jpg"


def source_path(finish) -> Path | None:
    named = finish.get("textureSource")
    if named:
        path = REPO / named
        if path.exists():
            return path
    dropin = drop_in_path(finish["id"])
    if dropin.exists():
        return dropin
    return None


def _smooth(t: np.ndarray) -> np.ndarray:
    return t * t * (3.0 - 2.0 * t)


def flatten_lighting(image: Image.Image) -> Image.Image:
    """Remove the slow vignette so opposite edges are the same brightness."""
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    radius = max(12, int(min(image.size) * 0.1))
    blur = np.asarray(image.filter(ImageFilter.GaussianBlur(radius=radius))).astype(np.float32)
    mean = arr.mean(axis=(0, 1), keepdims=True)
    out = arr - blur + mean
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def make_seamless(image: Image.Image) -> Image.Image:
    """Offset so the borders already tile, then restore the continuous centre.

    The blend is a wide ring, not a hard line. A narrow fade or a mirror
    leaves a visible seam; this keeps one uninterrupted patch of grain in
    the middle and only mixes similar wood near the edges.
    """
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    height, width, _ = arr.shape
    rolled = np.roll(np.roll(arr, width // 2, axis=1), height // 2, axis=0)
    yy, xx = np.mgrid[0:height, 0:width]
    dx = np.minimum(xx, width - 1 - xx).astype(np.float32)
    dy = np.minimum(yy, height - 1 - yy).astype(np.float32)
    ax = _smooth(np.clip(dx / (width * 0.28), 0.0, 1.0))
    ay = _smooth(np.clip(dy / (height * 0.28), 0.0, 1.0))
    alpha = (ax * ay)[..., None]
    out = arr * alpha + rolled * (1.0 - alpha)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def _cap(image: Image.Image) -> Image.Image:
    """Shrink only when a side exceeds MAX_TILE. Never upscale."""
    width, height = image.size
    longest = max(width, height)
    if longest <= MAX_TILE:
        return image
    scale = MAX_TILE / longest
    return image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)


def to_tile(image: Image.Image, preserve_aspect: bool) -> Image.Image:
    if preserve_aspect:
        return _cap(image)
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    return _cap(image.crop((left, top, left + side, top + side)))


def recolor(tile: Image.Image, target_rgb: np.ndarray, contrast: float) -> Image.Image:
    """Map grain onto target so the median pixel, not the highlights, is that colour."""
    arr = np.asarray(tile).astype(np.float32)
    lum = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    anchor = float(np.median(lum)) + 1e-6
    rel = (lum / anchor - 1.0) * contrast
    out = target_rgb.reshape(1, 1, 3) * (1.0 + rel[..., None])
    out = np.clip(out, 0, 255)
    for _ in range(4):
        med = np.median(out.reshape(-1, 3), axis=0)
        out = np.clip(out + (target_rgb - med).reshape(1, 1, 3), 0, 255)
    return Image.fromarray(out.astype(np.uint8), "RGB")


def grade(tile: Image.Image, contrast: float = 1.0, warmth: float = 0.0) -> Image.Image:
    """Stretch grain contrast and push the hue warmer (more red, less blue)."""
    arr = np.asarray(tile).astype(np.float32)
    lum = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    mean = float(lum.mean()) + 1e-6
    rel = np.clip((lum / mean - 1.0) * contrast + 1.0, 0.35, 1.85)
    out = arr * (rel / (lum / mean + 1e-6))[..., None]
    if warmth:
        out[:, :, 0] += warmth * 16.0
        out[:, :, 1] += warmth * 4.0
        out[:, :, 2] -= warmth * 12.0
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def along_grain(tile: Image.Image, radius: float) -> Image.Image:
    """Blur along the grain (horizontal) so pebble noise fades and long lines stay."""
    if radius <= 0:
        return tile
    arr = np.asarray(tile).astype(np.float32)
    span = max(1, int(round(radius * 2)))
    offsets = np.arange(-span, span + 1)
    kernel = np.exp(-0.5 * (offsets / radius) ** 2)
    kernel /= kernel.sum()
    out = np.zeros_like(arr)
    for weight, offset in zip(kernel, offsets):
        out += weight * np.roll(arr, int(offset), axis=1)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def denoise(tile: Image.Image) -> Image.Image:
    """Small bilateral pass. It drops JPEG grit and leaves the grain lines."""
    arr = np.asarray(tile).astype(np.float32)
    out = np.zeros_like(arr)
    norm = np.zeros(arr.shape[:2] + (1,), dtype=np.float32)
    sigma_r = 18.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            shifted = np.roll(np.roll(arr, dy, axis=0), dx, axis=1)
            dist2 = ((arr - shifted) ** 2).mean(axis=2, keepdims=True)
            spatial = np.exp(-0.5 * (dx * dx + dy * dy) / 1.4)
            weight = np.exp(-0.5 * dist2 / (sigma_r ** 2)) * spatial
            out += shifted * weight
            norm += weight
    return Image.fromarray(np.clip(out / norm, 0, 255).astype(np.uint8), "RGB")


def smooth_along_grain(tile: Image.Image, radius: int = 2) -> Image.Image:
    """Average along the grain so JPEG speckle goes, and the lines stay."""
    arr = np.asarray(tile).astype(np.float32)
    total = np.zeros_like(arr)
    for dx in range(-radius, radius + 1):
        total += np.roll(arr, dx, axis=1)
    return Image.fromarray(np.clip(total / (radius * 2 + 1), 0, 255).astype(np.uint8), "RGB")


def scale_luminance(tile: Image.Image, factor: float) -> Image.Image:
    """Darken or lighten without shifting hue. RGB scale keeps the grain ratios."""
    if factor == 1:
        return tile
    arr = np.asarray(tile).astype(np.float32) * float(factor)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def inpaint_red_streaks(tile: Image.Image) -> Image.Image:
    """Replace the thin red wire with the wood just above and below it.

    The wire collapses green and blue. Ordinary dark grain does not, so pores stay.
    """
    out = np.asarray(tile).astype(np.float32)
    for _ in range(3):
        redness = out[:, :, 0] - 0.5 * (out[:, :, 1] + out[:, :, 2])
        samples = np.stack([np.roll(out, dy, axis=0) for dy in (-8, -6, -5, -4, 4, 5, 6, 8)], 0)
        neighbor = np.median(samples, axis=0)
        neighbor_red = neighbor[:, :, 0] - 0.5 * (neighbor[:, :, 1] + neighbor[:, :, 2])
        wire = ((redness - neighbor_red) > 14) & (out[:, :, 1] < 40) & (out[:, :, 0] > 100)
        if not np.any(wire):
            break
        out[wire] = neighbor[wire]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def sharpen_along_grain(tile: Image.Image, amount: float = 0.18) -> Image.Image:
    """Very light contrast across the grain, after denoise. Not an isotropic unsharp."""
    if amount <= 0:
        return tile
    arr = np.asarray(tile).astype(np.float32)
    blur = (np.roll(arr, 1, axis=0) + arr + np.roll(arr, -1, axis=0)) / 3.0
    out = arr + (arr - blur) * amount
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def pore_emboss(tile: Image.Image, amount: float) -> Image.Image:
    """Subtle wrap-around lighting so pores keep depth after the tile is scaled down."""
    arr = np.asarray(tile).astype(np.float32)
    lum = arr.mean(axis=2)
    dx = np.roll(lum, -1, axis=1) - np.roll(lum, 1, axis=1)
    dy = np.roll(lum, -1, axis=0) - np.roll(lum, 1, axis=0)
    shade = (-0.55 * dx) + (-0.84 * dy)
    shade = shade / (float(np.std(shade)) + 1e-6)
    out = arr + shade[..., None] * (amount * 14.0)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def build_from_photo(finish) -> Image.Image:
    path = source_path(finish)
    image = Image.open(path).convert("RGB")
    crop = finish.get("textureCrop")
    if crop:
        x, y, w, h = crop
        image = image.crop((x, y, x + w, y + h))
    rotate = int(finish.get("textureRotate") or 0)
    if rotate:
        image = image.rotate(rotate, expand=True)
    tile = make_seamless(flatten_lighting(to_tile(image, bool(finish.get("preserveAspect")))))
    if finish.get("recolorToHex"):
        tile = recolor(tile, hex_to_rgb(finish["hex"]), float(finish.get("grainContrast", 1.0)))
    else:
        contrast = float(finish.get("grainContrast", 1.0))
        warmth = float(finish.get("warmth", 0.0))
        if contrast != 1.0 or warmth:
            tile = grade(tile, contrast, warmth)
    tile = denoise(tile)
    tile = smooth_along_grain(tile, radius=int(finish.get("alongGrainSmooth") or 2))
    amount = float(finish.get("alongGrainSharpen") or 0)
    if amount:
        tile = sharpen_along_grain(tile, amount)
    if finish.get("removeRedStreaks"):
        tile = inpaint_red_streaks(tile)
    scale = finish.get("luminanceScale")
    if scale:
        tile = scale_luminance(tile, float(scale))
    if max(tile.size) < 1024:
        print(f"WARNING  {finish['id']} is {tile.size[0]}x{tile.size[1]} (long side under 1024)")
    return tile


def main():
    TEXTURES.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    finishes = manifest["finishes"]
    walnut_finish = next(f for f in finishes if f["id"] == "WALNUT")
    walnut = build_from_photo(walnut_finish)
    walnut_path = TEXTURES / walnut_finish["texture"]
    walnut.save(walnut_path, quality=95, subsampling=0, optimize=True)
    print(f"catalogue  {walnut_path.name}")

    for finish in finishes:
        if finish.get("type") != "woodgrain" or finish["id"] == "WALNUT":
            continue
        dest = TEXTURES / finish["texture"]
        if source_path(finish):
            tile = build_from_photo(finish)
            tile.save(dest, quality=95, subsampling=0, optimize=True)
            print(f"catalogue  {dest.name}  {tile.size[0]}x{tile.size[1]}  rotate={finish.get('textureRotate', 0)}")
            continue
        contrast = float(finish.get("grainContrast", 1.0))
        tile = recolor(walnut, hex_to_rgb(finish["hex"]), contrast)
        tile.save(dest, quality=95, subsampling=0, optimize=True)
        print(f"interim    {dest.name}  toward {finish['hex']}")


if __name__ == "__main__":
    main()
