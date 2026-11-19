// Full-view glass on V130G / V230G. Part numbers live in
// part_number_service.resolve_gk17_alum_glass. A colour missing from
// STOCKED_COLORS has no GK17 kit for that treatment; the picker disables
// it. The backend still substitutes the nearest kit if a saved config
// already has that combo.
//
// TEMPERED + INSULATED is temp/clear (GK17-11000-00), the existing
// aluminum Tempered + Insulated choice. Thermal tempered is TEMP_TEMP
// (GK17-13000-00) and does not replace that mapping.

export const FULL_VIEW_TREATMENTS = [
  { id: 'standard', name: 'Standard', detail: 'Single annealed', pane: 'SINGLE', type: 'ANNEALED' },
  { id: 'thermal', name: 'Thermal', detail: 'Insulated clear/clear', pane: 'INSULATED', type: 'ANNEALED' },
  { id: 'tempered', name: 'Tempered', detail: 'Single tempered', pane: 'SINGLE', type: 'TEMPERED' },
  { id: 'thermal_tempered', name: 'Thermal tempered', detail: 'Insulated temp/temp', pane: 'INSULATED', type: 'TEMP_TEMP' },
]

export const FULL_VIEW_COLORS = [
  { id: 'CLEAR', name: 'Clear' },
  { id: 'ETCHED', name: 'Etched' },
  { id: 'SUPER_GREY', name: 'Super Grey' },
]

export const STOCKED_COLORS = {
  standard: ['CLEAR', 'ETCHED'],
  thermal: ['CLEAR', 'ETCHED', 'SUPER_GREY'],
  tempered: ['CLEAR'],
  thermal_tempered: ['CLEAR'],
  temp_clear: ['CLEAR', 'ETCHED'],
}

const TREATMENT_LABELS = {
  standard: 'Standard',
  thermal: 'Thermal',
  tempered: 'Tempered',
  thermal_tempered: 'Thermal tempered',
  temp_clear: 'Temp/clear',
}

export function fullViewTreatmentId(door) {
  const pane = door?.glassPaneType || 'INSULATED'
  const type = String(door?.glassType || 'ANNEALED').toUpperCase()
  if (pane === 'INSULATED' && type === 'TEMP_TEMP') return 'thermal_tempered'
  if (pane === 'SINGLE' && type === 'TEMPERED') return 'tempered'
  if (pane === 'INSULATED' && type === 'TEMPERED') return 'temp_clear'
  if (pane === 'SINGLE') return 'standard'
  return 'thermal'
}

export function colorStockedForTreatment(treatmentId, colorId) {
  return (STOCKED_COLORS[treatmentId] || []).includes(colorId || 'CLEAR')
}

export function selectFullViewTreatment(door, treatmentId) {
  const treatment = FULL_VIEW_TREATMENTS.find((item) => item.id === treatmentId)
  const current = door?.glassColor || 'CLEAR'
  const glassColor = colorStockedForTreatment(treatmentId, current) ? current : 'CLEAR'
  return {
    glassPaneType: treatment.pane,
    glassType: treatment.type,
    glassColor,
  }
}

export function fullViewGlassLabel(door) {
  const id = fullViewTreatmentId(door)
  const raw = String(door?.glassColor || 'CLEAR').replace(/_/g, ' ').toLowerCase()
  const color = raw.replace(/\b\w/g, (letter) => letter.toUpperCase())
  return `${TREATMENT_LABELS[id] || 'Thermal'}, ${color}`
}
