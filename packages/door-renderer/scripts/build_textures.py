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
# Cap only. Never enlarge a crop: upscaling is what turns grain lines into soft bands.
MAX_TILE = 1024


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


def make_seamless(image: Image.Image) -> Image.Image:
    """Blend a thin border so the tile repeats. The middle stays the sharp photo.

    Offsetting the whole image parks a seam through the grain. A short edge
    fade leaves the lines in the crop untouched.
    """
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    height, width, _ = arr.shape
    out = arr.copy()
    band_x = max(8, int(width * 0.04))
    band_y = max(4, int(height * 0.04))
    ramp_x = np.linspace(0.0, 1.0, band_x, dtype=np.float32)
    ramp_x = ramp_x * ramp_x * (3.0 - 2.0 * ramp_x)
    right = arr[:, -band_x:, :][:, ::-1, :]
    out[:, :band_x, :] = right * (1.0 - ramp_x.reshape(1, -1, 1)) + arr[:, :band_x, :] * ramp_x.reshape(1, -1, 1)
    ramp_y = np.linspace(0.0, 1.0, band_y, dtype=np.float32)
    ramp_y = ramp_y * ramp_y * (3.0 - 2.0 * ramp_y)
    bottom = arr[-band_y:, :, :][::-1, :, :]
    out[:band_y, :, :] = bottom * (1.0 - ramp_y.reshape(-1, 1, 1)) + arr[:band_y, :, :] * ramp_y.reshape(-1, 1, 1)
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
    arr = np.asarray(tile).astype(np.float32)
    lum = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    mean = float(lum.mean()) + 1e-6
    rel = (lum / mean - 1.0) * contrast
    out = target_rgb.reshape(1, 1, 3) * (1.0 + rel[..., None])
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


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


def sharpen_lines(tile: Image.Image, amount: float = 0.9, radius: float = 0.8) -> Image.Image:
    """Unsharp-mask the grain lines without amplifying photo noise into sand.

    Only edges stronger than a small threshold are boosted, so flat wood stays
    flat and the dark streaks stay thin.
    """
    blur = tile.filter(ImageFilter.GaussianBlur(radius=radius))
    original = np.asarray(tile).astype(np.float32)
    detail = original - np.asarray(blur).astype(np.float32)
    magnitude = np.abs(detail).mean(axis=2, keepdims=True)
    weight = np.clip((magnitude - 2.5) / 6.0, 0.0, 1.0)
    out = original + detail * amount * weight
    # Darken rows that are already darker than their neighbours (the grain lines).
    lum = 0.2126 * out[:, :, 0] + 0.7152 * out[:, :, 1] + 0.0722 * out[:, :, 2]
    padded = np.pad(lum, ((1, 1), (0, 0)), mode="wrap")
    neighbours = 0.5 * (padded[:-2] + padded[2:])
    line = np.clip(neighbours - lum, 0.0, 18.0)
    out -= (line * 0.55)[..., None]
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
    tile = make_seamless(to_tile(image, bool(finish.get("preserveAspect"))))
    if finish.get("recolorToHex"):
        tile = recolor(tile, hex_to_rgb(finish["hex"]), float(finish.get("grainContrast", 1.0)))
    else:
        contrast = float(finish.get("grainContrast", 1.0))
        warmth = float(finish.get("warmth", 0.0))
        if contrast != 1.0 or warmth:
            tile = grade(tile, contrast, warmth)
    emboss = finish.get("poreEmboss")
    if emboss:
        tile = pore_emboss(tile, float(emboss))
    # Sharpen last so colour grading and any pore shade cannot soften the lines again.
    amount = finish.get("sharpen")
    if amount is None:
        amount = 1.7
    if amount:
        tile = sharpen_lines(tile, float(amount))
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
