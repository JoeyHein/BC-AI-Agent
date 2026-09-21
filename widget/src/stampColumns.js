/**
 * Horizontal stamp / raised-panel count. Must match
 * frontend/src/utils/stampColumns.js and
 * backend/app/services/shop_drawings/framing.py (_stamp_columns).
 *
 * Long stamps (SHXL, BCXL): 4 rectangles through 16'11" (incl. 16'2");
 * 5 starting at 17'0".
 */

export function getStampColumns(widthInches, stampType = 'long', isCraft = false, panelDesign = '') {
  const widthFeet = Number(widthInches || 0) / 12

  let longCols
  if (widthFeet < 12) longCols = 2
  else if (widthFeet <= 14) longCols = 3
  else if (widthFeet < 17) longCols = 4
  else if (widthFeet <= 19) longCols = 5
  else longCols = 6

  if (isCraft) return longCols
  if (stampType === 'long') return longCols

  const isBronte = panelDesign === 'BC'
  if (isBronte) {
    if (widthFeet <= 10) return 4
    if (widthFeet <= 14) return 6
    if (widthFeet <= 16) return 8
    if (widthFeet <= 18) return 8
    return 10
  }

  if (widthFeet <= 9) return 4
  if (widthFeet <= 10) return 5
  if (widthFeet <= 12) return 6
  if (widthFeet <= 14) return 7
  if (widthFeet <= 16) return 8
  if (widthFeet <= 18) return 9
  return 10
}
