/**
 * Door Image Mapping Configuration
 * Maps door designs, colors, and sizes to actual product images from the Upwardor catalogue
 */

// Base path for door images
const DOOR_IMAGES_BASE = '/assets/doors'

// Design code to folder mapping
const DESIGN_FOLDERS = {
  // Kanata Collection
  SH: 'kanata/sheridan',
  SHXL: 'kanata/sheridan-xl',
  BC: 'kanata/bronte-creek',
  BCXL: 'kanata/bronte-creek-xl',
  TRAF: 'kanata/trafalgar',
  FLUSH: 'kanata/flush',
  // Craft Series
  MUSKOKA: 'craft/muskoka',
  DENISON: 'craft/denison',
  GRANVILLE: 'craft/granville',
}

// Color ID to filename mapping
const COLOR_FILES = {
  WHITE: 'white.jpg',
  BRIGHT_WHITE: 'white.jpg',
  NEW_ALMOND: 'new-almond.jpg',
  BLACK: 'black.jpg',
  WALNUT: 'walnut.jpg',
  IRON_ORE: 'iron-ore.jpg',
  SANDTONE: 'sandtone.jpg',
  NEW_BROWN: 'new-brown.jpg',
  BRONZE: 'bronze.jpg',
  STEEL_GREY: 'steel-grey.jpg',
  HAZELWOOD: 'hazelwood.jpg',
  ENGLISH_CHESTNUT: 'english-chestnut.jpg',
}

// Size-specific designs available (these have different panel layouts per size)
const SIZE_SPECIFIC_DESIGNS = ['SH', 'SHXL', 'BC', 'BCXL']

// Available sizes with size-specific images
const AVAILABLE_SIZES = ['8x7', '9x7', '10x7', '12x7', '14x7', '16x7']

/**
 * Get the image URL for a door configuration
 * @param {string} designCode - Panel design code (SH, SHXL, BC, etc.)
 * @param {string} colorId - Color ID (WHITE, WALNUT, etc.)
 * @param {number} widthFeet - Door width in feet
 * @param {number} heightFeet - Door height in feet
 * @returns {string|null} Image URL or null if not available
 */
export function getDoorImageUrl(designCode, colorId, widthFeet = 9, heightFeet = 7) {
  const designFolder = DESIGN_FOLDERS[designCode]
  const colorFile = COLOR_FILES[colorId] || 'white.jpg'

  if (!designFolder) {
    return null
  }

  // Check if we have a size-specific image
  if (SIZE_SPECIFIC_DESIGNS.includes(designCode)) {
    const sizeKey = `${widthFeet}x${heightFeet}`
    if (AVAILABLE_SIZES.includes(sizeKey)) {
      // Use size-specific image
      const sizeFolder = designFolder.split('/')[1] // Get design name part
      return `${DOOR_IMAGES_BASE}/sizes/${sizeFolder}/${sizeKey}/${colorFile}`
    }
  }

  // Fall back to main design image (generic)
  return `${DOOR_IMAGES_BASE}/${designFolder}/${colorFile}`
}

/**
 * Check if an image exists for a configuration
 * @param {string} designCode - Panel design code
 * @param {string} colorId - Color ID
 * @returns {boolean} True if image should exist
 */
export function hasImageForConfig(designCode, colorId) {
  return DESIGN_FOLDERS[designCode] && COLOR_FILES[colorId]
}

/**
 * Get all available colors for a design
 * @param {string} designCode - Panel design code
 * @returns {string[]} Array of available color IDs
 */
export function getAvailableColors(designCode) {
  // All Kanata designs have the same colors
  if (['SH', 'SHXL', 'BC', 'BCXL', 'TRAF', 'FLUSH'].includes(designCode)) {
    return ['WHITE', 'NEW_ALMOND', 'BLACK', 'WALNUT', 'SANDTONE', 'NEW_BROWN', 'BRONZE', 'STEEL_GREY', 'HAZELWOOD']
  }
  // Craft series has fewer colors
  if (['MUSKOKA', 'DENISON', 'GRANVILLE'].includes(designCode)) {
    return ['WHITE', 'SANDTONE', 'WALNUT', 'BLACK']
  }
  return ['WHITE']
}

/**
 * Get designs that have size-specific images
 */
export function getSizeSpecificDesigns() {
  return SIZE_SPECIFIC_DESIGNS
}

/**
 * Get available sizes for size-specific images
 */
export function getAvailableSizes() {
  return AVAILABLE_SIZES
}

export default {
  getDoorImageUrl,
  hasImageForConfig,
  getAvailableColors,
  getSizeSpecificDesigns,
  getAvailableSizes,
  DOOR_IMAGES_BASE,
  DESIGN_FOLDERS,
  COLOR_FILES,
}
