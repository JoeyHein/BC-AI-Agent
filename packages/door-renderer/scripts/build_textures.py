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
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "finishes.json"
TEXTURES = ROOT / "textures"
SOURCES = ROOT / "sources"
TILE = 512


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
    """Wrap the photo so its edges meet, then crossfade only a few pixels of the join.

    The fade is short on purpose. At door-preview size it is about a pixel, so
    the grain stays photographic instead of growing a mirrored or combed band.
    """
    image = image.convert("RGB")
    width, height = image.size
    shifted = np.roll(
        np.roll(np.asarray(image).astype(np.float32), width // 2, axis=1),
        height // 2,
        axis=0,
    )
    out = shifted.copy()
    band = 5
    ramp = np.linspace(0.0, 1.0, band * 2, dtype=np.float32)
    ramp = ramp * ramp * (3.0 - 2.0 * ramp)
    cx, cy = width // 2, height // 2
    left = shifted[:, cx - band - 1, :]
    right = shifted[:, cx + band + 1, :]
    out[:, cx - band : cx + band, :] = left[:, None, :] * (1.0 - ramp.reshape(1, -1, 1)) + right[:, None, :] * ramp.reshape(1, -1, 1)
    top = shifted[cy - band - 1, :, :]
    bottom = shifted[cy + band + 1, :, :]
    out[cy - band : cy + band, :, :] = top[None, :, :] * (1.0 - ramp.reshape(-1, 1, 1)) + bottom[None, :, :] * ramp.reshape(-1, 1, 1)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def to_tile(image: Image.Image) -> Image.Image:
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    square = image.crop((left, top, left + side, top + side))
    return square.resize((TILE, TILE), Image.Resampling.LANCZOS)


def recolor(tile: Image.Image, target_rgb: np.ndarray, contrast: float) -> Image.Image:
    arr = np.asarray(tile).astype(np.float32)
    lum = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    mean = float(lum.mean()) + 1e-6
    rel = (lum / mean - 1.0) * contrast
    out = target_rgb.reshape(1, 1, 3) * (1.0 + rel[..., None])
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
    tile = make_seamless(to_tile(image))
    emboss = finish.get("poreEmboss")
    if emboss:
        tile = pore_emboss(tile, float(emboss))
    return tile


def main():
    TEXTURES.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    finishes = manifest["finishes"]
    walnut_finish = next(f for f in finishes if f["id"] == "WALNUT")
    walnut = build_from_photo(walnut_finish)
    walnut_path = TEXTURES / walnut_finish["texture"]
    walnut.save(walnut_path, quality=86, optimize=True)
    print(f"catalogue  {walnut_path.name}")

    for finish in finishes:
        if finish.get("type") != "woodgrain" or finish["id"] == "WALNUT":
            continue
        dest = TEXTURES / finish["texture"]
        if source_path(finish):
            tile = build_from_photo(finish)
            tile.save(dest, quality=86, optimize=True)
            print(f"catalogue  {dest.name}  rotate={finish.get('textureRotate', 0)}")
            continue
        contrast = float(finish.get("grainContrast", 1.0))
        tile = recolor(walnut, hex_to_rgb(finish["hex"]), contrast)
        tile.save(dest, quality=86, optimize=True)
        print(f"interim    {dest.name}  toward {finish['hex']}")


if __name__ == "__main__":
    main()
