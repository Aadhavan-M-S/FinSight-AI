import { useEffect, useRef, useState } from 'react'
import { ArrowDownToLine, ChevronLeft, ChevronRight, Minus, Plus, X } from 'lucide-react'
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { apiRoot, type Citation } from './api'

GlobalWorkerOptions.workerSrc = workerUrl
export type ViewerSource = { id: string; name: string; citation?: Citation }

export default function PdfViewer({ source, onClose }: { source: ViewerSource; onClose: () => void }) {
  const [pdf, setPdf] = useState<PDFDocumentProxy>()
  const [page, setPage] = useState(source.citation?.page ?? 1)
  const [scale, setScale] = useState(1)
  const [error, setError] = useState('')
  const [size, setSize] = useState<[number, number]>([0, 0])
  const canvas = useRef<HTMLCanvasElement>(null)
  const url = apiRoot + '/documents/' + source.id + '/file'
  useEffect(() => {
    setPdf(undefined)
    setError('')
    let active = true
    const task = getDocument({ url, isEvalSupported: false })
    task.promise.then(document => { if (active) setPdf(document) })
      .catch(() => { if (active) setError('This PDF could not be opened.') })
    return () => { active = false; void task.destroy() }
  }, [url])
  useEffect(() => { setPage(source.citation?.page ?? 1) }, [source])
  useEffect(() => {
    if (!pdf || !canvas.current) return
    let active = true
    let cancel: (() => void) | undefined
    const target = canvas.current
    pdf.getPage(page).then(sourcePage => {
      if (!active) return
      const viewport = sourcePage.getViewport({ scale })
      const pixelRatio = Math.min(window.devicePixelRatio, 2)
      target.width = viewport.width * pixelRatio
      target.height = viewport.height * pixelRatio
      target.style.width = viewport.width + 'px'
      target.style.height = viewport.height + 'px'
      setSize([viewport.width, viewport.height])
      const task = sourcePage.render({
        canvasContext: target.getContext('2d')!, viewport,
        transform: [pixelRatio, 0, 0, pixelRatio, 0, 0],
      })
      cancel = () => task.cancel()
      return task.promise
    }).catch(() => { if (active) setError('This page could not be rendered.') })
    return () => { active = false; cancel?.() }
  }, [pdf, page, scale])
  const citation = source.citation?.page === page ? source.citation : undefined
  return <aside className="viewer" aria-label="Source PDF">
    <div className="viewer-title"><div><b>Source PDF</b><span title={source.name}>{source.name}</span></div>
      <a href={url} download title="Download PDF" aria-label="Download PDF"><ArrowDownToLine size={18} /></a>
      <button className="icon" onClick={onClose} aria-label="Close viewer"><X size={20} /></button>
    </div>
    <div className="viewer-bar">
      <button className="icon" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={18} /></button>
      <span>Page {page} of {pdf?.numPages ?? '…'}</span>
      <button className="icon" aria-label="Next page" disabled={!pdf || page >= pdf.numPages} onClick={() => setPage(page + 1)}><ChevronRight size={18} /></button>
      <button className="icon" aria-label="Zoom out" disabled={scale <= 0.5} onClick={() => setScale(scale - 0.25)}><Minus size={16} /></button>
      <span>{Math.round(scale * 100)}%</span>
      <button className="icon" aria-label="Zoom in" disabled={scale >= 2.5} onClick={() => setScale(scale + 0.25)}><Plus size={16} /></button>
    </div>
    {error && <p className="notice error" role="alert">{error}</p>}
    {!pdf && !error && <p className="notice" role="status">Opening PDF…</p>}
    {citation && <div className="viewer-excerpt"><b>{citation.section || 'Source excerpt'}</b>
      {citation.printed_page && <small>Printed page {citation.printed_page}</small>}
      <p>{citation.text}</p></div>}
    <div className="viewer-scroll">
      <div className="pdf-page" aria-label={`PDF page ${page}`}>
        <canvas ref={canvas} />
        {citation?.page_size && citation.boxes.map(([x0, y0, x1, y1], index) => {
          const [width, height] = citation.page_size!
          return <span key={index} className="highlight" style={{
            left: x0 / width * size[0], top: y0 / height * size[1],
            width: (x1 - x0) / width * size[0], height: (y1 - y0) / height * size[1],
          }} />
        })}
      </div>
    </div>
  </aside>
}
