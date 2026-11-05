// Aluminum / full-view doors standard is 3" track. 2" is a choice the
// user makes on the hardware step. Steel doors keep their own defaults
// (residential 2", commercial series set to 3" when that series is picked).

export const ALUMINUM_DOOR_SERIES = ['AL976', 'SWD', 'PANORAMA', 'SOLALITE']

export function isAluminumDoor(doorSeries, doorType) {
  const series = String(doorSeries || '').trim().toUpperCase()
  const type = String(doorType || '').trim().toLowerCase()
  return ALUMINUM_DOOR_SERIES.includes(series) || type === 'aluminium' || type === 'aluminum'
}

export function defaultTrackThickness(doorSeries, doorType) {
  return isAluminumDoor(doorSeries, doorType) ? '3' : '2'
}
