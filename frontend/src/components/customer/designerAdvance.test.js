import assert from 'node:assert/strict'
import test from 'node:test'
import {
  AUTO_ADVANCE_MS,
  shouldScheduleAutoAdvance,
  stepIsComplete,
} from './designerAdvance.js'

const kanata = { id: 'KANATA', name: 'Kanata', specs: { maxWidth: 288, maxHeight: 168 } }
const craft = {
  id: 'CRAFT',
  name: 'Craft',
  specs: { availableWidths: [96, 108, 144, 192], availableHeights: [84, 96] },
}

test('auto-advance waits about 300ms', () => {
  assert.equal(AUTO_ADVANCE_MS, 300)
})

test('door type advances only when the job name and the category are both set', () => {
  const door = { doorType: 'residential' }
  assert.equal(stepIsComplete('type', door, '  ', kanata), false)
  assert.equal(stepIsComplete('type', { doorType: '' }, 'Smith', kanata), false)
  assert.equal(stepIsComplete('type', door, 'Smith Residence', kanata), true)
  assert.equal(shouldScheduleAutoAdvance({
    stepId: 'type',
    complete: true,
    userActed: true,
  }), true)
  assert.equal(shouldScheduleAutoAdvance({
    stepId: 'type',
    complete: true,
    userActed: false,
    arrivedForward: true,
  }), false)
})

test('series, size, and design advance after the dealer fills every required field', () => {
  assert.equal(stepIsComplete('series', { doorSeries: '' }, 'Smith', kanata), false)
  assert.equal(stepIsComplete('series', { doorSeries: 'KANATA' }, 'Smith', kanata), true)

  const sized = { doorWidth: 192, doorHeight: 84, doorCount: 1 }
  assert.equal(stepIsComplete('dimensions', sized, 'Smith', kanata), true)
  assert.equal(stepIsComplete('dimensions', { ...sized, doorCount: 0 }, 'Smith', kanata), false)
  assert.equal(stepIsComplete('dimensions', { doorWidth: 120, doorHeight: 84, doorCount: 1 }, 'Smith', craft), false)
  assert.equal(shouldScheduleAutoAdvance({
    stepId: 'dimensions',
    complete: true,
    userActed: false,
  }), false)
  assert.equal(shouldScheduleAutoAdvance({
    stepId: 'dimensions',
    complete: true,
    userActed: true,
  }), true)

  assert.equal(stepIsComplete('design', { panelColor: 'BLACK', panelDesign: '' }, 'Smith', kanata), false)
  assert.equal(stepIsComplete('design', { panelColor: '', panelDesign: 'SH' }, 'Smith', kanata), false)
  assert.equal(stepIsComplete('design', { panelColor: 'BLACK', panelDesign: 'SH' }, 'Smith', kanata), true)
  assert.equal(stepIsComplete('design', { panelColor: 'CLEAR_ANODIZED', panelDesign: 'FLUSH' }, 'Smith', kanata), true)
})

test('windows and hardware never auto-advance, and Back does not bounce', () => {
  for (const stepId of ['windows', 'hardware']) {
    assert.equal(shouldScheduleAutoAdvance({
      stepId,
      complete: true,
      userActed: true,
      arrivedForward: true,
    }), false)
  }
  assert.equal(shouldScheduleAutoAdvance({
    stepId: 'series',
    complete: true,
    userActed: false,
    arrivedForward: false,
  }), false)
  assert.equal(shouldScheduleAutoAdvance({
    stepId: 'design',
    complete: true,
    userActed: false,
    arrivedForward: true,
  }), false)
})

test('drawings moves on only when Next opened it, and review does not', () => {
  assert.equal(stepIsComplete('drawings', {}, 'Smith', kanata), true)
  assert.equal(shouldScheduleAutoAdvance({
    stepId: 'drawings',
    complete: true,
    arrivedForward: true,
  }), true)
  assert.equal(shouldScheduleAutoAdvance({
    stepId: 'drawings',
    complete: true,
    arrivedForward: false,
    userActed: true,
  }), false)
  assert.equal(shouldScheduleAutoAdvance({
    stepId: 'review',
    complete: true,
    userActed: true,
    arrivedForward: true,
  }), false)
})
