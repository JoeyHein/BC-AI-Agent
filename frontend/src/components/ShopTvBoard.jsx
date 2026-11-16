import { useEffect, useMemo, useState } from 'react'

const ROTATE_MS = 12000
const DAY_PX = 36
const ITEM_PX = 96
const ARRIVAL_PX = 140
const ARRIVAL_DAY_PX = 32
const LANE_CHROME = 64
const EMPTY_PX = 40
const SHOP_TZ = 'America/Regina'

const LANES = [
  { id: 'production', title: 'Production', accent: 'text-amber-300', rule: 'border-amber-400' },
  { id: 'pickups', title: 'Pickups', accent: 'text-sky-300', rule: 'border-sky-400' },
  { id: 'deliveries', title: 'Deliveries', accent: 'text-emerald-300', rule: 'border-emerald-400' },
  { id: 'incoming', title: 'Incoming', accent: 'text-violet-300', rule: 'border-violet-400' },
  {
    id: 'upwardor',
    title: 'Arriving from Upwardor',
    accent: 'text-orange-300',
    rule: 'border-orange-400',
    titleClass: 'text-3xl',
  },
]

function kioskToken() {
  return new URLSearchParams(window.location.search).get('kiosk') || ''
}

function formatClock(date) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: SHOP_TZ,
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

function formatStamp(date) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: SHOP_TZ,
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

function formatDay(date) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: SHOP_TZ,
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  }).format(date)
}

function formatTime(value) {
  if (!value) return ''
  const [hourText, minuteText] = value.split(':')
  const hour = Number(hourText)
  const minute = Number(minuteText)
  if (Number.isNaN(hour) || Number.isNaN(minute)) return ''
  const suffix = hour >= 12 ? 'PM' : 'AM'
  const hour12 = hour % 12 || 12
  return `${hour12}:${String(minute).padStart(2, '0')} ${suffix}`
}

function formatEta(value) {
  if (!value) return 'No date'
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return 'No date'
  const date = new Date(Date.UTC(year, month - 1, day, 18))
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: SHOP_TZ,
    month: 'short',
    day: 'numeric',
  }).format(date)
}

function itemCount(days) {
  return (days || []).reduce((total, day) => total + ((day.items || []).length), 0)
}

function paginate(days, budget, itemPx = ITEM_PX, dayPx = DAY_PX) {
  const pages = []
  let page = []
  let used = 0
  const flush = () => {
    if (page.length) pages.push(page)
    page = []
    used = 0
  }
  for (const day of days || []) {
    const items = day.items || []
    if (items.length === 0) {
      const cost = dayPx + EMPTY_PX
      if (page.length && used + cost > budget) flush()
      page.push({ ...day, items: [] })
      used += cost
      continue
    }
    let index = 0
    while (index < items.length) {
      const room = budget - used - dayPx
      if (room < itemPx) {
        if (page.length === 0) {
          page.push({ ...day, items: items.slice(index, index + 1), continued: index > 0 })
          index += 1
          flush()
        } else {
          flush()
        }
        continue
      }
      const count = Math.min(items.length - index, Math.floor(room / itemPx))
      page.push({
        ...day,
        items: items.slice(index, index + count),
        continued: index > 0,
      })
      used += dayPx + count * itemPx
      index += count
      if (budget - used < dayPx + itemPx) flush()
    }
  }
  flush()
  return pages.length ? pages : [days || []]
}

function QuietScreen({ title, detail }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center overflow-hidden bg-[#071629] px-8 text-white">
      <div className="max-w-4xl text-center">
        <p className="text-sm font-semibold uppercase tracking-[0.35em] text-amber-300">Open Distribution</p>
        <h1 className="mt-6 text-5xl font-bold">{title}</h1>
        {detail && <p className="mt-6 text-2xl text-white/70">{detail}</p>}
      </div>
    </div>
  )
}

function DayBlock({ day }) {
  const overdue = Boolean(day.overdue)
  const today = Boolean(day.is_today)
  const headerClass = overdue
    ? 'text-red-300'
    : today
      ? 'text-amber-300'
      : 'text-white'
  return (
    <div>
      <div className="flex h-9 items-baseline gap-3">
        <h3 className={`text-2xl font-bold uppercase tracking-wide ${headerClass}`}>{day.label}</h3>
        {day.sublabel && (
          <span className={`text-lg ${overdue ? 'text-red-300/80' : 'text-white/60'}`}>{day.sublabel}</span>
        )}
        {day.continued && <span className="text-base text-white/40">continued</span>}
      </div>
      {day.items.length === 0 && (
        <p className="flex h-10 items-center text-xl text-white/40">Nothing scheduled</p>
      )}
      <ul>
        {day.items.map((item) => {
          const alert = item.overdue || item.late
          return (
            <li
              key={item.id}
              className={`flex h-[92px] flex-col justify-center rounded-lg border-l-4 px-4 ${
                alert
                  ? 'border-red-500 bg-red-950/80'
                  : today
                    ? 'border-amber-400/80 bg-amber-400/10'
                    : 'border-white/15 bg-white/10'
              }`}
            >
              <div className="flex items-baseline justify-between gap-4">
                <span className={`truncate font-mono text-2xl font-bold leading-none ${alert ? 'text-red-100' : 'text-white'}`}>
                  {item.order_number}
                </span>
                <span className={`shrink-0 text-2xl font-bold leading-none ${alert ? 'text-red-200' : 'text-white'}`}>
                  {formatTime(item.time)}
                </span>
              </div>
              <p className={`mt-1 truncate text-xl leading-tight ${alert ? 'text-red-100' : 'text-white/95'}`}>
                {item.customer || '—'}
              </p>
              {(item.destination || item.detail) && (
                <p className={`truncate text-lg leading-tight ${alert ? 'text-red-200' : 'text-white/75'}`}>
                  {item.destination || item.detail}
                  <span className={`ml-2 text-base font-semibold uppercase tracking-wide ${alert ? 'text-red-300' : 'text-white/45'}`}>
                    {item.when_label}
                  </span>
                </p>
              )}
              {!item.destination && !item.detail && (
                <p className={`text-base font-semibold uppercase tracking-wide ${alert ? 'text-red-300' : 'text-white/45'}`}>
                  {item.when_label}
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function ArrivalBlock({ day }) {
  const overdue = Boolean(day.overdue)
  const today = Boolean(day.is_today)
  const headerClass = overdue ? 'text-red-300' : today ? 'text-orange-200' : 'text-white'
  return (
    <div>
      <div className="flex h-8 items-baseline gap-3">
        <h3 className={`text-2xl font-bold uppercase tracking-wide ${headerClass}`}>{day.label}</h3>
        {day.sublabel && (
          <span className={`text-lg ${overdue ? 'text-red-300/80' : 'text-white/60'}`}>{day.sublabel}</span>
        )}
        {day.continued && <span className="text-base text-white/40">continued</span>}
      </div>
      <ul>
        {(day.items || []).map((item) => {
          const alert = item.overdue || item.late
          const completes = String(item.completion || '').startsWith('Completes')
          return (
            <li
              key={item.id}
              className={`flex h-[132px] flex-col justify-center overflow-hidden rounded-lg border-l-4 px-3 ${
                alert
                  ? 'border-red-500 bg-red-950/80'
                  : today
                    ? 'border-orange-300/80 bg-orange-400/10'
                    : 'border-white/15 bg-white/10'
              }`}
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className={`truncate font-mono text-2xl font-bold leading-none ${alert ? 'text-red-100' : 'text-white'}`}>
                  {item.order_number}
                </span>
                <span className={`shrink-0 text-xl font-bold leading-none ${alert ? 'text-red-200' : 'text-white'}`}>
                  {formatEta(item.date)}
                </span>
              </div>
              <div className="mt-1 flex items-baseline justify-between gap-3">
                <span className={`truncate font-mono text-xl leading-tight ${alert ? 'text-red-100' : 'text-orange-100'}`}>
                  {item.supplier_order_label || item.supplier_order_no || ''}
                </span>
                <span className={`shrink-0 text-lg font-semibold uppercase tracking-wide ${alert ? 'text-red-200' : 'text-white/80'}`}>
                  {item.status_label || item.when_label}
                </span>
              </div>
              <p className={`truncate text-xl leading-tight ${alert ? 'text-red-100' : 'text-white'}`}>
                {item.sales_label || 'STOCK'}
              </p>
              {item.summary && (
                <p className={`truncate text-lg leading-tight ${alert ? 'text-red-100' : 'text-white/90'}`}>
                  {item.summary}
                </p>
              )}
              {item.completion && (
                <p className={`truncate text-lg font-semibold leading-tight ${
                  alert ? 'text-red-200' : completes ? 'text-emerald-300' : 'text-amber-200'
                }`}
                >
                  {item.completion}
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Lane({ lane, days, budget, variant = 'standard', emptyLabel = '', grow = null, fitContent = false }) {
  const itemPx = variant === 'arrival' ? ARRIVAL_PX : ITEM_PX
  const dayPx = variant === 'arrival' ? ARRIVAL_DAY_PX : DAY_PX
  const [page, setPage] = useState(0)
  const pages = useMemo(() => paginate(days, budget, itemPx, dayPx), [days, budget, itemPx, dayPx])
  useEffect(() => {
    if (pages.length < 2) return undefined
    const timer = setInterval(() => setPage((value) => value + 1), ROTATE_MS)
    return () => clearInterval(timer)
  }, [pages.length])
  const index = pages.length ? page % pages.length : 0
  const visible = pages[index] || []
  const sized = fitContent ? 'shrink-0' : grow == null ? 'flex-1' : 'min-h-0'
  return (
    <section
      className={`flex ${sized} flex-col overflow-hidden rounded-2xl border border-white/10 bg-white/[0.04] ${lane.rule}`}
      style={fitContent || grow == null ? undefined : { flexGrow: grow, flexBasis: 0 }}
    >
      <div className="flex items-baseline justify-between gap-3 px-5 pt-4">
        <h2 className={`${lane.titleClass || 'text-4xl'} font-bold leading-none tracking-tight ${lane.accent}`}>{lane.title}</h2>
        {pages.length > 1 && (
          <span className="shrink-0 text-lg font-semibold text-white/50">{index + 1} / {pages.length}</span>
        )}
      </div>
      <div className={`${fitContent ? '' : 'min-h-0 flex-1'} overflow-hidden px-4 pb-3 pt-2`}>
        {visible.length === 0 && emptyLabel && (
          <p className="pt-4 text-2xl text-white/50">{emptyLabel}</p>
        )}
        {visible.map((day) => (
          variant === 'arrival' ? (
            <ArrivalBlock key={`${day.date || 'later'}-${day.continued ? 'c' : 'a'}-${day.items?.[0]?.id || 'empty'}`} day={day} />
          ) : (
            <DayBlock key={`${day.date}-${day.continued ? 'c' : 'a'}-${day.items?.[0]?.id || 'empty'}`} day={day} />
          )
        ))}
      </div>
    </section>
  )
}

function sampleBoard() {
  return {
    generated_at: new Date().toISOString(),
    timezone: 'America/Regina',
    today: '2026-11-16',
    horizon_days: 7,
    refresh_seconds: 60,
    incoming_enabled: true,
    sources: [{ id: 'business_central', available: true }],
    lanes: {
      upwardor: {
        days: [
          {
            date: '2026-11-10',
            label: 'Overdue',
            sublabel: 'Tue Nov 10',
            is_today: false,
            overdue: true,
            items: [
              {
                id: 'upwardor:PO-000948',
                order_number: 'PO-000948',
                supplier_order_label: 'S-ORD 116280',
                sales_label: 'SO-001800 North Hill Homes',
                summary: '1× 16x7 TX450 white sections + hardware',
                completion: 'Completes SO-001800',
                status_label: 'No ack',
                date: '2026-11-10',
                overdue: true,
                late: false,
              },
            ],
          },
          {
            date: '2026-11-16',
            label: 'Today',
            sublabel: 'Mon Nov 16',
            is_today: true,
            overdue: false,
            items: [
              {
                id: 'upwardor:PO-000962',
                order_number: 'PO-000962',
                supplier_order_label: 'S-ORD 116307',
                sales_label: 'SO-001842 Prairie Door Co',
                summary: '2× 10x7 Kanata white sections + hardware',
                completion: 'Completes SO-001842',
                status_label: 'Shipped',
                date: '2026-11-16',
                overdue: false,
                late: false,
              },
              {
                id: 'upwardor:PO-000970',
                order_number: 'PO-000970',
                supplier_order_label: 'S-ORD 116318',
                sales_label: 'SO-001900 Riverbend',
                summary: '1× 9x8 TX450 black sections + hardware',
                completion: 'SO-001900 also waiting on PO-000881',
                status_label: 'Acknowledged',
                date: '2026-11-16',
                overdue: false,
                late: false,
              },
            ],
          },
          {
            date: null,
            label: 'Later',
            sublabel: 'No date',
            is_today: false,
            overdue: false,
            later: true,
            items: [
              {
                id: 'upwardor:PO-000990',
                order_number: 'PO-000990',
                supplier_order_label: 'S-ORD 116340',
                sales_label: 'STOCK',
                summary: '4× 12\' Kanata white sections + hardware',
                completion: '',
                status_label: 'No ack',
                date: null,
                overdue: false,
                late: false,
              },
            ],
          },
        ],
      },
      incoming: {
        days: [
          {
            date: '2026-11-17',
            label: 'Tue Nov 17',
            sublabel: '',
            is_today: false,
            overdue: false,
            items: [
              {
                id: 'incoming:PO-000100',
                order_number: 'PO-000100',
                customer: 'Elton',
                detail: 'SO-000555 North Hill Homes',
                when_label: 'Expected',
                time: null,
                overdue: false,
                late: false,
              },
            ],
          },
        ],
      },
      production: {
        days: [
          {
            date: '2026-11-16',
            label: 'Today',
            sublabel: 'Mon Nov 16',
            is_today: true,
            overdue: false,
            items: [
              {
                id: 'production:SO-001842',
                order_number: 'SO-001842',
                customer: 'Prairie Door Co',
                detail: '10x7 Kanata white',
                when_label: 'Scheduled',
                time: '08:00',
                overdue: false,
                late: false,
              },
            ],
          },
        ],
      },
      pickups: {
        days: [
          {
            date: '2026-11-17',
            label: 'Tue Nov 17',
            sublabel: '',
            is_today: false,
            overdue: false,
            items: [
              {
                id: 'pickups:SO-001900',
                order_number: 'SO-001900',
                customer: 'Riverbend',
                detail: '9x8 TX450',
                when_label: 'Pickup',
                time: '14:00',
                overdue: false,
                late: false,
              },
            ],
          },
        ],
      },
      deliveries: {
        days: [
          {
            date: '2026-11-18',
            label: 'Wed Nov 18',
            sublabel: '',
            is_today: false,
            overdue: false,
            items: [
              {
                id: 'deliveries:SO-001800',
                order_number: 'SO-001800',
                customer: 'North Hill Homes',
                destination: '4500 Rochdale Blvd, Regina',
                when_label: 'Delivery',
                time: '10:30',
                overdue: false,
                late: false,
              },
            ],
          },
        ],
      },
    },
  }
}

function ShopTvBoard() {
  const [board, setBoard] = useState(null)
  const [phase, setPhase] = useState('loading')
  const [stale, setStale] = useState(false)
  const [now, setNow] = useState(() => new Date())
  const [budget, setBudget] = useState(860)

  useEffect(() => {
    const previousHtml = document.documentElement.style.overflow
    const previousBody = document.body.style.overflow
    document.documentElement.style.overflow = 'hidden'
    document.body.style.overflow = 'hidden'
    document.title = 'Shop TV'
    return () => {
      document.documentElement.style.overflow = previousHtml
      document.body.style.overflow = previousBody
    }
  }, [])

  useEffect(() => {
    const clock = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(clock)
  }, [])

  useEffect(() => {
    const measure = () => {
      const available = window.innerHeight - 88 - 72 - 16
      setBudget(Math.max(360, available))
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  useEffect(() => {
    const token = kioskToken()
    const samplePreview = import.meta.env.DEV && new URLSearchParams(window.location.search).get('sample') === '1'
    if (samplePreview) {
      setBoard(sampleBoard())
      setStale(false)
      setPhase('ready')
      return undefined
    }
    let cancelled = false
    const load = async () => {
      const headers = { Accept: 'application/json' }
      if (token) headers['X-Shop-Tv-Token'] = token
      else {
        const staff = localStorage.getItem('authToken')
        if (staff) headers.Authorization = `Bearer ${staff}`
      }
      try {
        const response = await fetch('/api/shop-tv/board', { headers, cache: 'no-store' })
        if (cancelled) return
        if (response.status === 404) {
          setPhase('off')
          return
        }
        if (response.status === 401 || response.status === 403) {
          setPhase('denied')
          setBoard(null)
          return
        }
        if (!response.ok) {
          setStale(true)
          setPhase((current) => (current === 'ready' ? 'ready' : 'error'))
          return
        }
        const payload = await response.json()
        setBoard(payload)
        setStale(false)
        setPhase('ready')
      } catch (error) {
        if (cancelled) return
        setStale(true)
        setPhase((current) => (current === 'ready' ? 'ready' : 'error'))
      }
    }
    load()
    const refreshMs = 60000
    const timer = setInterval(load, refreshMs)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  if (phase === 'loading') {
    return <QuietScreen title="Loading shop board" />
  }
  if (phase === 'off') {
    return (
      <QuietScreen
        title="Shop TV is off"
        detail="Turn it on in Settings when the shop is ready to cast this screen."
      />
    )
  }
  if (phase === 'denied' || phase === 'error' || !board) {
    return (
      <QuietScreen
        title={phase === 'denied' ? 'This shop link is not active' : 'Shop board could not be loaded'}
        detail="The screen keeps trying. Ask an admin to check the shop TV link in Settings."
      />
    )
  }

  const updated = board.generated_at ? formatStamp(new Date(board.generated_at)) : ''
  const bcDown = (board.sources || []).some((source) => source.id === 'business_central' && source.available === false)
  const lanes = board.incoming_enabled ? LANES : LANES.filter((lane) => lane.id !== 'incoming' && lane.id !== 'upwardor')
  const upwardorDays = board.lanes?.upwardor?.days || []
  const incomingDays = board.lanes?.incoming?.days || []
  const upwardorCount = itemCount(upwardorDays)
  const incomingCount = itemCount(incomingDays)
  let upwardorBudget = Math.max(ARRIVAL_PX + ARRIVAL_DAY_PX, budget - LANE_CHROME)
  let incomingBudget = budget
  if (upwardorCount && incomingCount) {
    const column = budget + 72
    const incomingReserve = 56 + DAY_PX + Math.min(incomingCount, 2) * ITEM_PX + 28
    upwardorBudget = Math.max(ARRIVAL_PX + ARRIVAL_DAY_PX, column - incomingReserve - 52)
    incomingBudget = incomingReserve
  } else if (!upwardorCount && incomingCount) {
    upwardorBudget = 120
    incomingBudget = Math.max(ITEM_PX + DAY_PX, budget - upwardorBudget - LANE_CHROME)
  }

  return (
    <div className="fixed inset-0 z-[100] flex flex-col overflow-hidden bg-[#071629] text-white">
      <header className="flex h-[5.5rem] shrink-0 items-end justify-between px-8 pb-2">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.35em] text-amber-300">Open Distribution</p>
          <h1 className="text-4xl font-bold leading-none">Shop board</h1>
        </div>
        <div className="text-right">
          <p className="text-5xl font-bold leading-none tabular-nums">{formatClock(now)}</p>
          <p className="mt-1 text-lg text-white/70">{formatDay(now)}</p>
        </div>
        <div className="min-w-[16rem] text-right">
          <p className={`text-xl font-semibold ${stale ? 'text-red-400' : 'text-white/80'}`}>
            {stale ? 'Update failed' : 'Updated'}
          </p>
          <p className={`text-2xl font-bold tabular-nums ${stale ? 'text-red-300' : 'text-white'}`}>{updated}</p>
        </div>
      </header>
      {bcDown && (
        <p className="mx-8 mb-2 rounded-lg bg-red-950 px-4 py-2 text-xl font-semibold text-red-200">
          Business Central could not be read. Nothing new is on the board.
        </p>
      )}
      <div className="grid min-h-0 flex-1 grid-cols-3 gap-3 px-4 pb-4">
        {board.incoming_enabled && (
          <div className="flex min-h-0 flex-col gap-3">
            <Lane
              lane={lanes.find((lane) => lane.id === 'upwardor')}
              days={upwardorDays}
              budget={upwardorBudget}
              variant="arrival"
              emptyLabel="Nothing open from Upwardor"
              grow={!upwardorCount && incomingCount ? 0.28 : null}
            />
            {incomingCount > 0 && (
              <Lane
                lane={lanes.find((lane) => lane.id === 'incoming')}
                days={incomingDays}
                budget={incomingBudget}
                fitContent={upwardorCount > 0}
              />
            )}
          </div>
        )}
        <Lane
          lane={lanes.find((lane) => lane.id === 'production')}
          days={board.lanes?.production?.days || []}
          budget={budget}
        />
        {board.incoming_enabled ? (
          <div className="flex min-h-0 flex-col gap-3">
            <Lane
              lane={lanes.find((lane) => lane.id === 'pickups')}
              days={board.lanes?.pickups?.days || []}
              budget={Math.max(160, Math.floor((budget - 12) / 2))}
            />
            <Lane
              lane={lanes.find((lane) => lane.id === 'deliveries')}
              days={board.lanes?.deliveries?.days || []}
              budget={Math.max(160, Math.floor((budget - 12) / 2))}
            />
          </div>
        ) : (
          <>
            <Lane
              lane={lanes.find((lane) => lane.id === 'pickups')}
              days={board.lanes?.pickups?.days || []}
              budget={budget}
            />
            <Lane
              lane={lanes.find((lane) => lane.id === 'deliveries')}
              days={board.lanes?.deliveries?.days || []}
              budget={budget}
            />
          </>
        )}
      </div>
    </div>
  )
}

export default ShopTvBoard
