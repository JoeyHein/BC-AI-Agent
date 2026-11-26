import assert from 'node:assert/strict'
import test from 'node:test'
import {
  doorForPreviewPrice,
  formatDealerPrice,
  previewPropsFromDoor,
  priceSignature,
  quoteReadyForPreview,
} from './designerPreview.js'

test('residential preview follows colour, design, and windows', () => {
  const plain = previewPropsFromDoor({
    doorType: 'residential',
    doorSeries: 'KANATA',
    doorWidth: 192,
    doorHeight: 84,
    panelColor: 'WHITE',
    panelDesign: 'SH',
    hasWindows: false,
    windowInsert: 'STOCKTON_STANDARD',
  })
  assert.equal(plain.doorType, 'residential')
  assert.equal(plain.doorSeries, 'KANATA')
  assert.equal(plain.color, 'WHITE')
  assert.equal(plain.panelDesign, 'SH')
  assert.equal(plain.width, 192)
  assert.equal(plain.windowInsert, null)
  assert.deepEqual(plain.windowPositions, [])

  const black = previewPropsFromDoor({
    ...plain,
    doorType: 'residential',
    doorSeries: 'KANATA',
    panelColor: 'BLACK',
    panelDesign: 'FLUSH',
    hasWindows: true,
    windowInsert: 'STOCKTON_STANDARD',
    windowPositions: [{ section: 1, col: 0 }],
  })
  assert.equal(black.color, 'BLACK')
  assert.equal(black.panelDesign, 'FLUSH')
  assert.equal(black.windowInsert, 'STOCKTON_STANDARD')
  assert.equal(black.windowPositions.length, 1)
  const priced = doorForPreviewPrice({
    doorType: 'residential',
    doorSeries: 'KANATA',
    panelColor: '',
    panelDesign: '',
  })
  assert.equal(priced.panelColor, 'WHITE')
  assert.equal(priced.panelDesign, 'SHXL')
  assert.equal(doorForPreviewPrice({
    doorType: 'commercial',
    doorSeries: 'TX450',
    panelColor: 'WHITE',
    panelDesign: 'UDC',
  }).panelDesign, 'UDC')
})

test('commercial preview uses the commercial series and hides windows until asked', () => {
  const door = previewPropsFromDoor({
    doorType: 'commercial',
    doorSeries: 'TX450',
    doorWidth: 144,
    doorHeight: 96,
    panelColor: 'WHITE',
    panelDesign: 'UDC',
    hasWindows: false,
    windowQty: 4,
    windowInsert: '24X12',
  })
  assert.equal(door.doorType, 'commercial')
  assert.equal(door.doorSeries, 'TX450')
  assert.equal(door.panelDesign, 'UDC')
  assert.equal(door.windowInsert, null)
  assert.equal(door.windowQty, 0)
  assert.equal(door.windowFrameColor, 'BLACK')

  const glazed = previewPropsFromDoor({
    doorType: 'commercial',
    doorSeries: 'TX760',
    doorWidth: 144,
    doorHeight: 96,
    panelColor: 'WHITE',
    panelDesign: 'MICROGROOVE',
    hasWindows: true,
    windowInsert: '24X12',
    windowQty: 3,
    windowPanels: { 1: { qty: 3 } },
  })
  assert.equal(glazed.panelDesign, 'MICROGROOVE')
  assert.equal(glazed.windowInsert, '24X12')
  assert.equal(glazed.windowQty, 3)
  assert.deepEqual(glazed.windowPanels, { 1: { qty: 3 } })
})

test('aluminum preview is a full-view door in the selected finish and glass', () => {
  const door = previewPropsFromDoor({
    doorType: 'aluminium',
    doorSeries: 'AL976',
    doorWidth: 96,
    doorHeight: 84,
    panelColor: 'BLACK_ANODIZED',
    glassColor: 'SUPER_GREY',
    glassPaneType: 'INSULATED',
    glassPocketsPerSection: { 0: 4 },
    hasWindows: false,
  })
  assert.equal(door.doorType, 'aluminium')
  assert.equal(door.doorSeries, 'AL976')
  assert.equal(door.color, 'BLACK_ANODIZED')
  assert.equal(door.panelDesign, 'FLUSH')
  assert.equal(door.glassColor, 'SUPER_GREY')
  assert.deepEqual(door.glassPocketsPerSection, { 0: 4 })
})

test('a new door still draws, and the price waits for series and size', () => {
  const blank = previewPropsFromDoor({})
  assert.equal(blank.color, 'WHITE')
  assert.equal(blank.panelDesign, 'SHXL')
  assert.equal(blank.doorType, 'residential')
  assert.equal(quoteReadyForPreview([]), false)
  assert.equal(quoteReadyForPreview([{ doorSeries: '', doorWidth: 96, doorHeight: 84 }]), false)
  assert.equal(quoteReadyForPreview([
    { doorSeries: 'KANATA', doorWidth: 192, doorHeight: 84 },
    { doorSeries: 'TX450', doorWidth: 144, doorHeight: 96 },
    { doorSeries: 'AL976', doorWidth: 96, doorHeight: 84 },
  ]), true)
})

test('price signature ignores door identity and follows the options', () => {
  const base = {
    door_uid: 'a',
    doorType: 'residential',
    doorSeries: 'KANATA',
    panelColor: 'WHITE',
    doorWidth: 192,
    doorHeight: 84,
  }
  const same = priceSignature([base], 'delivery')
  assert.equal(priceSignature([{ ...base, door_uid: 'b' }], ''), same)
  assert.notEqual(priceSignature([{ ...base, panelColor: 'BLACK' }], 'delivery'), same)
  assert.notEqual(priceSignature([base], 'pickup'), same)
  assert.match(formatDealerPrice(1234.5), /1,234\.50/)
})
