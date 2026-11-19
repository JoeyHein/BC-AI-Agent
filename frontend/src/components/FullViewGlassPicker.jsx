import {
  FULL_VIEW_COLORS,
  FULL_VIEW_TREATMENTS,
  colorStockedForTreatment,
  fullViewTreatmentId,
  selectFullViewTreatment,
} from '../utils/fullViewGlass'

export default function FullViewGlassPicker({ door, onChange }) {
  const treatmentId = fullViewTreatmentId(door)
  const unstocked = FULL_VIEW_COLORS.filter(
    (color) => !colorStockedForTreatment(treatmentId, color.id)
  )

  return (
    <>
      <div className="mt-3">
        <label className="block text-sm font-medium text-gray-700 mb-1">Glass</label>
        <div className="flex flex-wrap gap-2">
          {FULL_VIEW_TREATMENTS.map((treatment) => (
            <button
              key={treatment.id}
              type="button"
              onClick={() => onChange(selectFullViewTreatment(door, treatment.id))}
              className={`px-4 py-2 text-sm rounded-md border text-left ${
                treatmentId === treatment.id
                  ? 'border-odc-500 bg-odc-100 text-odc-700'
                  : 'border-gray-300 hover:border-gray-400'
              }`}
            >
              <span className="block font-medium">{treatment.name}</span>
              <span className="block text-xs text-gray-500">{treatment.detail}</span>
            </button>
          ))}
        </div>
        {treatmentId === 'temp_clear' && (
          <p className="mt-2 text-xs text-gray-600">
            This door is insulated temp/clear, the existing Tempered + Insulated kit.
            Choose a glass above to change it.
          </p>
        )}
      </div>
      <div className="mt-3">
        <label className="block text-sm font-medium text-gray-700 mb-1">Glass color</label>
        <div className="flex flex-wrap gap-2">
          {FULL_VIEW_COLORS.map((color) => {
            const stocked = colorStockedForTreatment(treatmentId, color.id)
            const selected = (door.glassColor || 'CLEAR') === color.id
            return (
              <button
                key={color.id}
                type="button"
                disabled={!stocked}
                title={stocked ? color.name : `${color.name} is not stocked for this glass`}
                onClick={() => onChange({ glassColor: color.id })}
                className={`px-4 py-2 text-sm rounded-md border ${
                  !stocked
                    ? 'border-gray-200 bg-gray-50 text-gray-400 cursor-not-allowed'
                    : selected
                      ? 'border-odc-500 bg-odc-100 text-odc-700'
                      : 'border-gray-300 hover:border-gray-400'
                }`}
              >
                <span className="block font-medium">{color.name}</span>
                {!stocked && <span className="block text-xs">Not stocked</span>}
              </button>
            )
          })}
        </div>
        {unstocked.length > 0 && (
          <p className="mt-2 text-xs text-gray-500">
            {unstocked.map((color) => color.name).join(' and ')} {unstocked.length === 1 ? 'is' : 'are'} not
            stocked for this glass, so {unstocked.length === 1 ? 'that color is' : 'those colors are'} unavailable.
            A saved configuration that already uses one quotes the nearest kit and flags the substitution.
          </p>
        )}
      </div>
    </>
  )
}
