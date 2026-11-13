import { useEffect, useMemo, useState } from 'react'

const ROTATE_MS = 12000
const DAY_PX = 36
const ITEM_PX = 96
const EMPTY_PX = 40
const SHOP_TZ = 'America/Regina'

const LANES = [
  { id: 'production', title: 'Production', accent: 'text-amber-300', rule: 'border-amber-400' },
  { id: 'pickups', title: 'Pickups', accent: 'text-sky-300', rule: 'border-sky-400' },
  { id: 'deliveries', title: 'Deliveries', accent: 'text-emerald-300', rule: 'border-emerald-400' },
  { id: 'incoming', title: 'Incoming', accent: 'text-violet-300', rule: 'border-violet-400' },
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

function paginate(days, budget) {
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
      const cost = DAY_PX + EMPTY_PX
      if (page.length && used + cost > budget) flush()
      page.push({ ...day, items: [] })
      used += cost
      continue
    }
    let index = 0
    while (index < items.length) {
      const room = budget - used - DAY_PX
      if (room < ITEM_PX) {
        if (page.length === 0) {
          page.push({ ...day, items: items.slice(index, index + 1), continued: index > 0 })
          index += 1
          flush()
        } else {
          flush()
        }
        continue
      }
      const count = Math.min(items.length - index, Math.floor(room / ITEM_PX))
      page.push({
        ...day,
        items: items.slice(index, index + count),
        continued: index > 0,
      })
      used += DAY_PX + count * ITEM_PX
      index += count
      if (budget - used < DAY_PX + ITEM_PX) flush()
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

function Lane({ lane, days, page, pageCount, budget }) {
  const pages = useMemo(() => paginate(days, budget), [days, budget])
  const index = pages.length ? page % pages.length : 0
  const visible = pages[index] || []
  return (
    <section className={`flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-white/10 bg-white/[0.04] ${lane.rule}`}>
      <div className="flex items-baseline justify-between px-5 pt-4">
        <h2 className={`text-4xl font-bold tracking-wide ${lane.accent}`}>{lane.title}</h2>
        {pages.length > 1 && (
          <span className="text-lg font-semibold text-white/50">{index + 1} / {pages.length}</span>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-hidden px-4 pb-3 pt-2">
        {visible.map((day) => (
          <DayBlock key={`${day.date}-${day.continued ? 'c' : 'a'}-${day.items?.[0]?.id || 'empty'}`} day={day} />
        ))}
      </div>
    </section>
  )
}

function ShopTvBoard() {
  const [board, setBoard] = useState(null)
  const [phase, setPhase] = useState('loading')
  const [stale, setStale] = useState(false)
  const [now, setNow] = useState(() => new Date())
  const [tick, setTick] = useState(0)
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
    const rotate = setInterval(() => setTick((value) => value + 1), ROTATE_MS)
    return () => {
      clearInterval(clock)
      clearInterval(rotate)
    }
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
  const lanes = board.incoming_enabled ? LANES : LANES.filter((lane) => lane.id !== 'incoming')
  const maxPages = Math.max(
    1,
    ...lanes.map((lane) => paginate(board.lanes?.[lane.id]?.days || [], budget).length),
  )

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
          <Lane
            lane={lanes.find((lane) => lane.id === 'incoming')}
            days={board.lanes?.incoming?.days || []}
            page={tick}
            pageCount={maxPages}
            budget={budget}
          />
        )}
        <Lane
          lane={lanes.find((lane) => lane.id === 'production')}
          days={board.lanes?.production?.days || []}
          page={tick}
          pageCount={maxPages}
          budget={budget}
        />
        {board.incoming_enabled ? (
          <div className="flex min-h-0 flex-col gap-3">
            <Lane
              lane={lanes.find((lane) => lane.id === 'pickups')}
              days={board.lanes?.pickups?.days || []}
              page={tick}
              pageCount={maxPages}
              budget={Math.max(160, Math.floor((budget - 12) / 2))}
            />
            <Lane
              lane={lanes.find((lane) => lane.id === 'deliveries')}
              days={board.lanes?.deliveries?.days || []}
              page={tick}
              pageCount={maxPages}
              budget={Math.max(160, Math.floor((budget - 12) / 2))}
            />
          </div>
        ) : (
          <>
            <Lane
              lane={lanes.find((lane) => lane.id === 'pickups')}
              days={board.lanes?.pickups?.days || []}
              page={tick}
              pageCount={maxPages}
              budget={budget}
            />
            <Lane
              lane={lanes.find((lane) => lane.id === 'deliveries')}
              days={board.lanes?.deliveries?.days || []}
              page={tick}
              pageCount={maxPages}
              budget={budget}
            />
          </>
        )}
      </div>
    </div>
  )
}

export default ShopTvBoard
