/**
 * Drawing Export Utilities
 * Functions to export door drawings as SVG, PNG, or PDF
 */

import { jsPDF } from 'jspdf'

/**
 * Export SVG element as SVG file
 */
export function exportAsSVG(svgElement, filename = 'drawing.svg') {
  if (!svgElement) {
    console.error('No SVG element provided')
    return
  }

  // Clone the SVG to avoid modifying the original
  const clonedSvg = svgElement.cloneNode(true)

  // Add XML declaration and doctype
  const svgData = new XMLSerializer().serializeToString(clonedSvg)
  const svgBlob = new Blob(
    ['<?xml version="1.0" encoding="UTF-8"?>\n', svgData],
    { type: 'image/svg+xml;charset=utf-8' }
  )

  // Create download link
  const downloadLink = document.createElement('a')
  downloadLink.href = URL.createObjectURL(svgBlob)
  downloadLink.download = filename
  document.body.appendChild(downloadLink)
  downloadLink.click()
  document.body.removeChild(downloadLink)
  URL.revokeObjectURL(downloadLink.href)
}

/**
 * Export SVG element as PNG file
 */
export function exportAsPNG(svgElement, filename = 'drawing.png', scale = 2) {
  if (!svgElement) {
    console.error('No SVG element provided')
    return Promise.reject('No SVG element provided')
  }

  return new Promise((resolve, reject) => {
    // Get SVG dimensions
    const svgRect = svgElement.getBoundingClientRect()
    const width = svgRect.width * scale
    const height = svgRect.height * scale

    // Create canvas
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')

    // Fill with white background
    ctx.fillStyle = 'white'
    ctx.fillRect(0, 0, width, height)

    // Create image from SVG
    const svgData = new XMLSerializer().serializeToString(svgElement)
    const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(svgBlob)

    const img = new Image()
    img.onload = () => {
      ctx.drawImage(img, 0, 0, width, height)
      URL.revokeObjectURL(url)

      // Convert to PNG and download
      canvas.toBlob((blob) => {
        const downloadLink = document.createElement('a')
        downloadLink.href = URL.createObjectURL(blob)
        downloadLink.download = filename
        document.body.appendChild(downloadLink)
        downloadLink.click()
        document.body.removeChild(downloadLink)
        URL.revokeObjectURL(downloadLink.href)
        resolve()
      }, 'image/png')
    }
    img.onerror = reject
    img.src = url
  })
}

/**
 * Print drawing (opens print dialog)
 */
export function printDrawing(svgElement, title = 'Door Drawing') {
  if (!svgElement) {
    console.error('No SVG element provided')
    return
  }

  // Create print window
  const printWindow = window.open('', '_blank', 'width=800,height=600')

  if (!printWindow) {
    alert('Please allow popups to print the drawing')
    return
  }

  // Clone and serialize SVG
  const svgData = new XMLSerializer().serializeToString(svgElement)

  // Create print document
  printWindow.document.write(`
    <!DOCTYPE html>
    <html>
      <head>
        <title>${title}</title>
        <style>
          @page {
            size: landscape;
            margin: 0.5in;
          }
          body {
            margin: 0;
            padding: 20px;
            font-family: Arial, sans-serif;
          }
          .header {
            text-align: center;
            margin-bottom: 20px;
          }
          .header h1 {
            margin: 0;
            font-size: 18px;
          }
          .header p {
            margin: 5px 0 0 0;
            font-size: 12px;
            color: #666;
          }
          .drawing {
            display: flex;
            justify-content: center;
          }
          svg {
            max-width: 100%;
            height: auto;
          }
          .footer {
            margin-top: 20px;
            text-align: center;
            font-size: 10px;
            color: #999;
          }
          @media print {
            .no-print { display: none; }
          }
        </style>
      </head>
      <body>
        <div class="header">
          <h1>${title}</h1>
          <p>Generated: ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString()}</p>
        </div>
        <div class="drawing">
          ${svgData}
        </div>
        <div class="footer">
          Open DC - Door Configuration System
        </div>
        <script>
          window.onload = function() {
            window.print();
            // window.close();
          }
        </script>
      </body>
    </html>
  `)
  printWindow.document.close()
}

/**
 * Export multiple drawings as a combined PDF-ready document
 */
export function exportDrawingPackage(drawings, doorInfo) {
  // Create a combined view for all drawings
  const printWindow = window.open('', '_blank', 'width=1000,height=800')

  if (!printWindow) {
    alert('Please allow popups to export the drawing package')
    return
  }

  // Build content for each drawing
  const drawingContents = drawings.map(({ element, title }, index) => {
    if (!element) return ''
    const svgData = new XMLSerializer().serializeToString(element)
    return `
      <div class="page" ${index > 0 ? 'style="page-break-before: always;"' : ''}>
        <h2>${title}</h2>
        <div class="drawing">${svgData}</div>
      </div>
    `
  }).join('')

  printWindow.document.write(`
    <!DOCTYPE html>
    <html>
      <head>
        <title>Door Drawing Package</title>
        <style>
          @page {
            size: letter landscape;
            margin: 0.5in;
          }
          * {
            box-sizing: border-box;
          }
          body {
            margin: 0;
            padding: 0;
            font-family: Arial, sans-serif;
          }
          .cover {
            height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            page-break-after: always;
          }
          .cover h1 {
            font-size: 32px;
            margin-bottom: 20px;
          }
          .cover .info {
            font-size: 14px;
            color: #666;
          }
          .cover .info p {
            margin: 8px 0;
          }
          .page {
            padding: 20px;
          }
          .page h2 {
            text-align: center;
            margin-bottom: 20px;
            font-size: 16px;
          }
          .drawing {
            display: flex;
            justify-content: center;
          }
          svg {
            max-width: 100%;
            height: auto;
            max-height: 80vh;
          }
          .buttons {
            position: fixed;
            top: 10px;
            right: 10px;
            display: flex;
            gap: 10px;
          }
          .buttons button {
            padding: 10px 20px;
            font-size: 14px;
            cursor: pointer;
            border: none;
            border-radius: 4px;
          }
          .btn-print {
            background: #0066CC;
            color: white;
          }
          .btn-close {
            background: #666;
            color: white;
          }
          @media print {
            .buttons { display: none; }
          }
        </style>
      </head>
      <body>
        <div class="buttons">
          <button class="btn-print" onclick="window.print()">Print / Save PDF</button>
          <button class="btn-close" onclick="window.close()">Close</button>
        </div>

        <div class="cover">
          <h1>DOOR DRAWING PACKAGE</h1>
          <div class="info">
            <p><strong>Door:</strong> ${doorInfo.series || 'Custom'} - ${doorInfo.width || '?'}' x ${doorInfo.height || '?'}'</p>
            <p><strong>Color:</strong> ${doorInfo.color || 'N/A'}</p>
            <p><strong>Generated:</strong> ${new Date().toLocaleDateString()}</p>
            <p><strong>Document contains:</strong> ${drawings.length} drawings</p>
          </div>
        </div>

        ${drawingContents}

      </body>
    </html>
  `)
  printWindow.document.close()
}

/**
 * Export SVG element as PDF file (landscape, fits to page)
 */
export function exportAsPDF(svgElement, filename = 'drawing.pdf', title = '') {
  if (!svgElement) {
    console.error('No SVG element provided')
    return Promise.reject('No SVG element provided')
  }

  return new Promise((resolve, reject) => {
    // Get viewBox or bounding rect for aspect ratio
    const viewBox = svgElement.getAttribute('viewBox')
    let svgW, svgH
    if (viewBox) {
      const parts = viewBox.split(/\s+|,/)
      svgW = parseFloat(parts[2])
      svgH = parseFloat(parts[3])
    } else {
      const rect = svgElement.getBoundingClientRect()
      svgW = rect.width
      svgH = rect.height
    }

    // Determine orientation from aspect ratio
    const landscape = svgW >= svgH
    const orientation = landscape ? 'landscape' : 'portrait'

    // Page dimensions in mm (letter size)
    const pageW = landscape ? 279.4 : 215.9
    const pageH = landscape ? 215.9 : 279.4
    const margin = 10 // mm
    const usableW = pageW - margin * 2
    const usableH = pageH - margin * 2 - (title ? 10 : 0)

    // Scale SVG to fit page
    const scaleX = usableW / svgW
    const scaleY = usableH / svgH
    const fitScale = Math.min(scaleX, scaleY)
    const imgW = svgW * fitScale
    const imgH = svgH * fitScale

    // Render SVG to canvas at 2x for quality
    const renderScale = 2
    const canvas = document.createElement('canvas')
    canvas.width = svgW * renderScale
    canvas.height = svgH * renderScale
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = 'white'
    ctx.fillRect(0, 0, canvas.width, canvas.height)

    const svgData = new XMLSerializer().serializeToString(svgElement)
    const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(svgBlob)

    const img = new Image()
    img.onload = () => {
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)

      const imgData = canvas.toDataURL('image/png')

      const pdf = new jsPDF({ orientation, unit: 'mm', format: 'letter' })

      // Title
      if (title) {
        pdf.setFontSize(12)
        pdf.text(title, pageW / 2, margin + 4, { align: 'center' })
      }

      // Center image on page
      const offsetX = margin + (usableW - imgW) / 2
      const offsetY = margin + (title ? 10 : 0) + (usableH - imgH) / 2
      pdf.addImage(imgData, 'PNG', offsetX, offsetY, imgW, imgH)

      // Footer
      pdf.setFontSize(7)
      pdf.setTextColor(150)
      pdf.text(
        `Open DC - Generated ${new Date().toLocaleDateString()}`,
        pageW / 2, pageH - 5,
        { align: 'center' }
      )

      pdf.save(filename)
      resolve()
    }
    img.onerror = reject
    img.src = url
  })
}

/**
 * Get SVG element from a React ref or DOM selector
 */
export function getSvgFromRef(ref) {
  if (!ref) return null
  if (ref.current) {
    return ref.current.querySelector('svg')
  }
  return ref.querySelector ? ref.querySelector('svg') : null
}
