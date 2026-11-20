/**
 * Finish catalogue. Hex values, names, and texture files live in finishes.json.
 * This module only resolves those records for the renderer and for swatches.
 * It does not know which brand offers which finish.
 */

import manifest from '../finishes.json'

const textureModules = import.meta.glob('../textures/*.{jpg,jpeg,png,webp}', {
  eager: true,
  query: '?inline',
  import: 'default',
})

function textureUrlFor(filename) {
  if (!filename) return null
  const hit = Object.entries(textureModules).find(([key]) => key.endsWith('/' + filename))
  return hit ? hit[1] : null
}

const FINISH_LIST = manifest.finishes.map((finish) => ({
  ...finish,
  textureUrl: textureUrlFor(finish.texture),
}))

const BY_ID = Object.fromEntries(FINISH_LIST.map((finish) => [finish.id, finish]))

export function listFinishes() {
  return FINISH_LIST
}

export function getFinish(id) {
  if (!id) return null
  return BY_ID[id] || null
}

export function isWoodgrain(id) {
  const finish = getFinish(id)
  return Boolean(finish?.type === 'woodgrain' && finish.textureUrl)
}

export function hasMetallicSheen(id) {
  return Boolean(getFinish(id)?.sheen)
}

export function colorHex(id) {
  const hex = getFinish(id)?.hex
  return hex || null
}

/** CSS style for a colour chip. Woodgrains use the texture; everything else uses the hex. */
export function swatchStyle(id, fallbackHex) {
  const finish = getFinish(id)
  if (finish?.textureUrl) {
    return {
      backgroundImage: `url("${finish.textureUrl}")`,
      backgroundSize: 'cover',
      backgroundPosition: 'center',
    }
  }
  return { backgroundColor: finish?.hex || fallbackHex || '#ccc' }
}

/**
 * Fill an options object's colorData from the manifest.
 * Family colour lists stay in the options file; names and hexes do not.
 */
export function hydrateColorData(options) {
  const colorData = {}
  for (const finish of FINISH_LIST) {
    colorData[finish.id] = {
      hex: finish.hex,
      name: finish.name,
      type: finish.type,
      light: finish.light,
      dark: finish.dark,
      textureUrl: finish.textureUrl,
      textureStatus: finish.textureStatus || null,
    }
  }
  return { ...options, colorData }
}
