/**
 * When the dealer quote builder moves itself to the next step.
 * Windows and Hardware stay put until Next. A finished step that was
 * opened with Back does not move until the dealer changes it again.
 */

import { getDimensionValidation } from '../../utils/doorDimensions.js'

export const AUTO_ADVANCE_MS = 300

const MANUAL_STEPS = new Set(['windows', 'hardware'])

export function stepIsComplete(stepId, door, quoteName, series) {
  switch (stepId) {
    case 'type':
      return Boolean(door?.doorType) && Boolean(String(quoteName || '').trim())
    case 'series':
      return Boolean(door?.doorSeries)
    case 'dimensions': {
      const width = Number(door?.doorWidth) || 0
      const height = Number(door?.doorHeight) || 0
      const count = Number(door?.doorCount) || 0
      const { errors } = getDimensionValidation(series, width, height)
      return width > 0 && height > 0 && count > 0 && errors.length === 0
    }
    case 'design':
      return Boolean(door?.panelColor) && Boolean(door?.panelDesign)
    case 'windows':
    case 'hardware':
    case 'drawings':
      return true
    case 'review':
      return Boolean(String(quoteName || '').trim())
    default:
      return false
  }
}

/**
 * @param {object} args
 * @param {string} args.stepId
 * @param {boolean} args.complete
 * @param {boolean} args.userActed True after an edit on this visit.
 * @param {boolean} args.arrivedForward True when Next opened this step.
 */
export function shouldScheduleAutoAdvance({ stepId, complete, userActed = false, arrivedForward = false }) {
  if (!complete) return false
  if (MANUAL_STEPS.has(stepId) || stepId === 'review') return false
  if (stepId === 'drawings') return arrivedForward
  return userActed
}
