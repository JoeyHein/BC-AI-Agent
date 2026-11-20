import { createRoot } from 'react-dom/client'
import DoorPreview from './components/DoorPreview'
import { getFinish } from 'door-renderer'

function finishLabel(design, color) {
  const finish = getFinish(color)
  const status = finish?.textureStatus === 'interim' ? ' — interim texture' : ''
  return `${design} ${color}${status}`
}

const WOOD = ['WALNUT', 'ENGLISH_CHESTNUT', 'FRENCH_OAK']
const DESIGNS = [
  { id: 'SHXL', series: '' },
  { id: 'SH', series: '' },
  { id: 'BCXL', series: '' },
  { id: 'MUSKOKA', series: 'CRAFT' },
]

function Cell({ label, children }) {
  return (
    <div style={{ background: '#fff', padding: 8, width: 280 }}>
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6, color: '#111' }}>{label}</div>
      {children}
    </div>
  )
}

const door = (extra) => (
  <DoorPreview
    width={192}
    height={84}
    showDimensions={false}
    scale={0.62}
    {...extra}
  />
)

function Gallery() {
  const detail = new URLSearchParams(window.location.search).has('detail')
  if (detail) {
    return (
      <div style={{ padding: 16, background: '#fff' }}>
        {['WALNUT', 'ENGLISH_CHESTNUT', 'FRENCH_OAK'].map((color) => (
          <div key={color} style={{ marginBottom: 16 }}>
            <div style={{ fontWeight: 700, marginBottom: 6 }}>{finishLabel('SHXL 16×7', color)}</div>
            <DoorPreview width={192} height={84} color={color} panelDesign="SHXL" showDimensions={false} scale={1.1} />
          </div>
        ))}
      </div>
    )
  }
  return (
    <div style={{ padding: 16 }}>
      <h1 style={{ fontSize: 16, margin: '0 0 12px' }}>Door renderer — 16×7</h1>
      <h2 style={{ fontSize: 13, margin: '0 0 8px' }}>Three woodgrain doors on one page</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {WOOD.map((color) => (
          <Cell key={color} label={finishLabel('SHXL', color)}>
            {door({ color, panelDesign: 'SHXL' })}
          </Cell>
        ))}
      </div>
      {DESIGNS.map((design) => (
        <div key={design.id} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          {WOOD.map((color) => (
            <Cell key={color} label={finishLabel(design.id, color)}>
              {door({
                color,
                panelDesign: design.id,
                doorSeries: design.series,
                doorType: 'residential',
              })}
            </Cell>
          ))}
        </div>
      ))}
      <h2 style={{ fontSize: 13, margin: '12px 0 8px' }}>Solid colours and a windowed door</h2>
      <div style={{ display: 'flex', gap: 8 }}>
        <Cell label="SHXL WHITE">
          {door({ color: 'WHITE', panelDesign: 'SHXL' })}
        </Cell>
        <Cell label="SHXL BLACK">
          {door({ color: 'BLACK', panelDesign: 'SHXL' })}
        </Cell>
        <Cell label="SHXL STEEL_GREY">
          {door({ color: 'STEEL_GREY', panelDesign: 'SHXL' })}
        </Cell>
        <Cell label="SHXL WALNUT + Stockton MATCH">
          {door({
            color: 'WALNUT',
            panelDesign: 'SHXL',
            windowInsert: 'STOCKTON_STANDARD',
            windowPositions: [{ section: 1, col: 0 }, { section: 1, col: 2 }],
            windowFrameColor: 'MATCH',
            hasInserts: true,
          })}
        </Cell>
      </div>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<Gallery />)
