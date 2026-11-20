# door-renderer

Shared sectional-door preview and the single finish catalogue. No dealer name, logo, or colour list of “what we sell” lives here. A brand decides which finish ids to offer.

## Use it

Point a Vite alias at `src/index.js`:

```js
alias: { 'door-renderer': path.resolve(__dirname, '../packages/door-renderer/src/index.js') }
```

```jsx
import DoorPreview, { swatchStyle, hydrateColorData } from 'door-renderer'
```

Another repo can copy this folder (or depend on it) and do the same. Keep brand chrome in the host app.

## Add or replace a finish texture

1. Put a flat photo at `sources/<id-with-hyphens>.jpg` (English Chestnut is `sources/english-chestnut.jpg`). Avoid frames, glare, and anything that is not the finish.
2. In `finishes.json`, set `texture`, `textureSource`, `textureCrop` (`[x, y, width, height]`), and `textureRotate` if the photo’s grain is not already the way the door is installed. Kanata and Craft woodgrain both run **horizontally** across the section. A section stood on end needs `"textureRotate": 90`.
3. Set `textureStatus` to `"catalogue"`, `grainAxis` to `"horizontal"` or `"vertical"`, `grainTile` (SVG units; smaller reads as tighter grain), and `hex` to the crop’s midtone.
4. Run:

```bash
python packages/door-renderer/scripts/build_textures.py
```

The script writes `textures/<texture>`. If a woodgrain finish has no photo, the script tints the walnut tile toward `hex` and that finish should stay `"textureStatus": "interim"`.

`poreEmboss` (0 to about 0.5) bakes a light wrap-around shade so pores keep a little depth when the tile is scaled down.
