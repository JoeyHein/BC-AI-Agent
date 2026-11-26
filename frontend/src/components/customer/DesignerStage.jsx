import { useEffect, useState } from 'react'
import DoorPreview from '../DoorPreview'
import { formatDealerPrice, previewPropsFromDoor } from './designerPreview'

function useNarrowScreen() {
  const [narrow, setNarrow] = useState(false)
  useEffect(() => {
    const query = window.matchMedia('(max-width: 1023px)')
    const apply = () => setNarrow(query.matches)
    apply()
    query.addEventListener('change', apply)
    return () => query.removeEventListener('change', apply)
  }, [])
  return narrow
}

function DesignerStage({
  door,
  doorIndex = 0,
  doorCount = 1,
  running = null,
  runningStatus = 'idle',
  official = null,
  deliveryType = 'delivery',
}) {
  const narrow = useNarrowScreen()
  const preview = previewPropsFromDoor(door)
  const series = door?.doorSeries
  const size = door?.doorWidth && door?.doorHeight
    ? `${Math.floor(door.doorWidth / 12)}'${door.doorWidth % 12 ? ` ${door.doorWidth % 12}"` : ''} × ${Math.floor(door.doorHeight / 12)}'${door.doorHeight % 12 ? ` ${door.doorHeight % 12}"` : ''}`
    : 'Size not set'
  const officialPricing = official?.pricing
  const runningPricing = running?.pricing
  const pricing = officialPricing || runningPricing
  const showAmount = pricing && Number(pricing.total) > 0
  const freight = running?.freight
  const caption = doorCount > 1 ? `Door ${doorIndex + 1} of ${doorCount}` : 'This door'

  let priceLabel = 'Running estimate'
  let priceText = 'Set the series and size to see a price'
  let note = 'The drawing updates as you choose. Request pricing on Review for the official quote.'
  const freightRate = freight?.rate
  const freightSentence = deliveryType === 'pickup' || freight?.skip
    ? 'Pickup, no freight.'
    : freightRate
      ? `Freight ${Number(freightRate)}%.`
      : 'Freight included.'
  if (officialPricing && showAmount) {
    priceLabel = 'Dealer price'
    priceText = formatDealerPrice(officialPricing.total, officialPricing.currency)
    note = official.bc_quote_number
      ? `Official quote ${official.bc_quote_number}`
      : 'Official quote from your price list'
  } else if (runningStatus === 'loading' && !showAmount) {
    priceText = 'Pricing…'
  } else if (runningStatus === 'error') {
    priceText = 'Price on Review'
    note = 'The running estimate did not come back. Review still builds the official quote.'
  } else if (showAmount) {
    priceText = formatDealerPrice(runningPricing.total, runningPricing.currency)
    note = `Running estimate. ${freightSentence} Review builds the official quote.`
  } else if (runningStatus === 'ready') {
    priceText = 'Price on Review'
    note = 'This configuration did not return a dealer total. Review still builds the official quote.'
  }

  return (
    <aside
      data-testid="designer-stage"
      className="sticky top-0 z-30 order-1 border-b border-gray-200 bg-white shadow-sm lg:top-4 lg:order-2 lg:z-10 lg:self-start lg:border-0 lg:bg-transparent lg:shadow-none"
    >
      <div className="lg:rounded-xl lg:border lg:border-gray-200 lg:bg-white lg:shadow">
        <div className="flex items-center gap-3 px-3 py-2 lg:block lg:px-4 lg:py-4">
          <div
            className="flex h-28 w-28 shrink-0 items-center justify-center lg:h-auto lg:w-full"
            data-testid="door-render"
            data-type={preview.doorType}
            data-series={preview.doorSeries}
            data-panel={preview.panelDesign}
            data-colour={preview.color}
            data-windows={preview.windowInsert || 'none'}
          >
            <DoorPreview
              {...preview}
              showDimensions={!narrow}
              maxWidth={narrow ? 96 : 230}
              scale={1}
            />
          </div>
          <div className="min-w-0 flex-1 lg:mt-3">
            <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{caption}</p>
            <p className="truncate text-sm font-medium text-gray-900">
              {series || 'Choose a series'}
              <span className="font-normal text-gray-500"> · {size}</span>
            </p>
            <p className="mt-1 text-xs text-gray-500" data-testid="designer-price-label">{priceLabel}</p>
            <p className="text-lg font-semibold text-gray-900" data-testid="designer-price">{priceText}</p>
            <p className="mt-1 text-xs leading-snug text-gray-500" data-testid="designer-price-note">{note}</p>
          </div>
        </div>
      </div>
    </aside>
  )
}

export default DesignerStage
