import { lazy, Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ArrowRight, ArrowUp, BookOpen, ChartNoAxesCombined, CheckCircle2, ChevronRight, CircleHelp,
  FileSearch, Files, FileText, FlaskConical, History, LayoutDashboard, Menu, Plus, RefreshCw, Search, Trash2, UploadCloud,
} from 'lucide-react'
import { api, amount, date, json, label, upload, type Citation, type Message, type Mode, type Report,
  type Session, type Status } from './api'
import type { ViewerSource } from './PdfViewer'

const Comparison = lazy(() => import('./Comparison'))
const Benchmarks = lazy(() => import('./BenchmarkLibrary'))
const PdfViewer = lazy(() => import('./PdfViewer'))

const navigation = [
  { id: 'overview', title: 'Overview', icon: LayoutDashboard, description: 'Manage your financial research in one workspace.' },
  { id: 'library', title: 'Document library', icon: Files, description: 'Upload and manage your financial reports.' },
  { id: 'single', title: 'Document chat', icon: FileText, description: 'Ask questions using evidence from one report.' },
  { id: 'research', title: 'Multi-document research', icon: FileSearch, description: 'Analyze a selected group of reports together.' },
  { id: 'compare', title: 'Company comparison', icon: ChartNoAxesCombined, description: 'Compare source-linked figures across companies and fiscal years.' },
  { id: 'history', title: 'Research history', icon: History, description: 'Find and reopen your saved conversations.' },
  { id: 'benchmarks', title: 'Benchmark Library', icon: FlaskConical, description: 'Explore publisher datasets and measure performance on controlled financial tasks.' },
] as const
type Page = typeof navigation[number]['id']
const reportName = (report: Report) => report.company_name || report.filename
const ready = (report: Report) => report.status === 'completed'
const pageFromHash = (): Page => navigation.find(item => '#' + item.id === location.hash)?.id ?? 'overview'

function StatePill({ report }: { report: Report }) {
  return <span className={'pill ' + report.status}>{ready(report) ? 'Ready' : report.status === 'failed' ? 'Failed' : 'Processing'}</span>
}

function Empty({ title, text, action }: { title: string; text: string; action?: React.ReactNode }) {
  return <div className="empty"><span className="empty-icon"><BookOpen size={23} /></span><h3>{title}</h3><p>{text}</p>{action}</div>
}

export default function Workspace() {
  const [page, setPage] = useState<Page>(pageFromHash)
  const [reports, setReports] = useState<Report[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [status, setStatus] = useState<Status>()
  const [active, setActive] = useState<Session>()
  const [source, setSource] = useState<ViewerSource>()
  const [menu, setMenu] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const [documents, history, system] = await Promise.all([
        api<Report[]>('/documents'), api<Session[]>('/chat/sessions'), api<Status>('/system/status'),
      ])
      setReports(documents)
      setSessions(history)
      setStatus(system)
      setError('')
    } catch (err) { setError((err as Error).message) } finally { setLoading(false) }
  }, [])
  useEffect(() => {
    void refresh()
    const onHash = () => { setPage(pageFromHash()); setSource(undefined) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [refresh])
  const processing = reports.filter(report => report.status === 'pending' || report.status === 'processing').length
  useEffect(() => {
    if (!processing) return
    const timer = setInterval(() => void refresh(), 1600)
    return () => clearInterval(timer)
  }, [processing, refresh])

  function go(next: Page) {
    setPage(next); setSource(undefined); setMenu(false)
    if (location.hash !== '#' + next) history.pushState(null, '', '#' + next)
  }
  function open(session: Session) {
    setActive(session)
    go(session.mode)
  }
  function cite(citation: Citation) {
    setSource({ id: citation.document_id, name: citation.document_name, citation })
  }

  const current = navigation.find(item => item.id === page)!
  const indexed = reports.filter(ready)
  const companies = new Set(indexed.map(report => report.company_id).filter(Boolean))
  const years = new Set(indexed.map(report => report.year).filter(Boolean))
  const recent = (items: Session[]) => <ul className="row-list">{items.map(session => <li key={session.id}>
    <button onClick={() => open(session)}><span className="tile-icon"><History size={17}/></span>
      <span className="row-label"><b>{session.title}</b><small>{session.document_ids.length} {session.document_ids.length === 1 ? 'report' : 'reports'} · {date(session.updated_at)}</small></span>
      <ChevronRight size={16}/></button>
  </li>)}</ul>

  return <div className="shell">
    <aside className={'sidebar' + (menu ? ' expanded' : '')}>
      <button className="brand" onClick={() => go('overview')} aria-label="FinSight AI overview">
        <span className="brand-icon"><ChartNoAxesCombined size={23} strokeWidth={2.5}/></span><span>FinSight<span className="brand-ai"> AI</span></span>
      </button>
      <nav aria-label="Workspace">
        {navigation.map(item => <button key={item.id} onClick={() => go(item.id)} aria-current={page === item.id ? 'page' : undefined}>
          <item.icon size={18}/><span>{item.title}</span>
        </button>)}
      </nav>
      <div className="sidebar-foot"><span className={error ? 'offline' : ''}/>{loading ? 'Connecting…' : error ? 'Workspace offline' : 'Local workspace'}</div>
    </aside>
    <main className="workspace">
      <header className="topbar">
        <button className="icon mobile-menu" onClick={() => setMenu(!menu)} aria-label="Toggle navigation"><Menu size={22}/></button>
        <span>Workspace <ChevronRight size={14}/> <b>{current.title}</b></span>
        <button className="outline" onClick={() => go('library')}><Plus size={17}/> Upload reports</button>
      </header>
      <div className="body">
        <div className="page-heading"><h1>{current.title}</h1><p>{current.description}</p></div>
        {error && <p role="alert" className="notice error">{error} <button className="link" onClick={() => void refresh()}>Retry</button></p>}
        {loading && <p role="status" className="notice">Loading workspace…</p>}
        {!loading && <div className={source ? 'with-viewer' : ''}>
          <div className="page-content">
            {page === 'overview' && <>
              <div className="stats">
                {[
                  { title: 'Uploaded reports', value: reports.length, icon: Files },
                  { title: 'Indexed companies', value: companies.size, icon: ChartNoAxesCombined },
                  { title: 'Fiscal years', value: years.size, icon: History },
                  { title: 'Processing', value: processing, icon: RefreshCw },
                ].map(item => <section className="stat" key={item.title}><item.icon size={19}/><span>{item.title}</span><strong>{item.value}</strong></section>)}
              </div>
              <div className="hero"><div><h2>Start with a financial report</h2>
                <p>Upload an annual report or filing to explore financial figures, ask questions, and trace answers back to the source.</p></div>
                <button onClick={() => go('library')}><UploadCloud size={18}/> Upload a PDF</button></div>
              <div className="overview-grid">
                <section className="panel"><div className="panel-heading"><h2>Recent uploads</h2><button className="link" onClick={() => go('library')}>View library <ArrowRight size={15}/></button></div>
                  {reports.length ? <ul className="row-list">{reports.slice(0, 5).map(report => <li key={report.id}>
                    <button onClick={() => setSource({ id: report.id, name: report.filename })}>
                      <span className="tile-icon"><FileText size={17}/></span><span className="row-label"><b>{reportName(report)}</b><small>{report.filename}</small></span>
                      <StatePill report={report}/>
                    </button></li>)}</ul> : <Empty title="No reports yet" text="Your uploaded documents will appear here."/>}</section>
                <section className="panel"><div className="panel-heading"><h2>Recent research</h2><button className="link" onClick={() => go('history')}>View history <ArrowRight size={15}/></button></div>
                  {sessions.length ? recent(sessions.slice(0, 5)) : <Empty title="No saved sessions" text="Start a chat to save your research here."/>}</section>
              </div>
              {status && <div className="system"><CheckCircle2 size={16}/> Workspace connected · {status.dense_retrieval ? 'Hybrid search configured' : 'Lexical search'} · {status.provider === 'mock' ? 'Mock provider' : status.groq_key_configured ? 'Groq key configured' : 'Groq key missing'}</div>}
            </>}
            {page === 'library' && <Library reports={reports} refresh={refresh} preview={report => setSource({ id: report.id, name: report.filename })}/>}
            {(page === 'single' || page === 'research') && <Research key={page} mode={page} reports={reports}
              session={active?.mode === page ? active : undefined} open={setActive} clear={() => setActive(undefined)}
              cite={cite} refresh={refresh} status={status} goLibrary={() => go('library')}/>}
            {page === 'compare' && <Suspense fallback={<p role="status" className="notice">Loading comparison…</p>}><Comparison reports={reports} cite={cite}/></Suspense>}
            {page === 'history' && <HistoryList sessions={sessions} reports={reports} open={open} refresh={refresh}/>}
            {page === 'benchmarks' && <Suspense fallback={<p role="status" className="notice">Loading benchmarks…</p>}><Benchmarks groqConfigured={!!status?.groq_key_configured}/></Suspense>}
          </div>
          {source && <Suspense fallback={<p role="status" className="notice">Loading viewer…</p>}><PdfViewer source={source} onClose={() => setSource(undefined)}/></Suspense>}
        </div>}
      </div>
    </main>
  </div>
}

function Library({ reports, refresh, preview }: { reports: Report[]; refresh: () => Promise<void>; preview: (report: Report) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [selected, setSelected] = useState<File[]>([])
  const [company, setCompany] = useState('')
  const [year, setYear] = useState('')
  const [filter, setFilter] = useState('')
  const [state, setState] = useState('')
  const [percent, setPercent] = useState<number>()
  const [drag, setDrag] = useState(false)
  const [error, setError] = useState('')
  const [acting, setActing] = useState('')
  const [remove, setRemove] = useState<Report>()
  function choose(files: File[]) {
    setError('')
    if (files.length > 10) { setError('Choose at most ten PDFs per upload.'); return }
    if (files.some(item => !item.name.toLowerCase().endsWith('.pdf'))) { setError('Choose PDF files.'); return }
    setSelected(files)
  }
  async function send(event: FormEvent) {
    event.preventDefault()
    if (!selected.length) return
    const form = new FormData()
    selected.forEach(file => form.append('files', file))
    if (company.trim()) form.append('company', company.trim())
    if (year) form.append('year', year)
    setPercent(0); setError('')
    try {
      const result = await upload(form, setPercent)
      if (result.errors.length) setError(result.errors.map(item => item.filename + ' · ' + item.message).join('\n'))
      setSelected([]); setCompany(''); setYear('')
      if (input.current) input.current.value = ''
      await refresh()
    } catch (err) { setError((err as Error).message) } finally { setPercent(undefined) }
  }
  async function change(report: Report, deleting: boolean) {
    setActing(report.id); setError('')
    try {
      await api('/documents/' + report.id + (deleting ? '' : '/reprocess'), { method: deleting ? 'DELETE' : 'POST' })
      setRemove(undefined)
      await refresh()
    } catch (err) { setError((err as Error).message) } finally { setActing('') }
  }
  const visible = reports.filter(report => (!state || report.status === state) &&
    [report.filename, report.company_name, report.year].some(value => String(value ?? '').toLowerCase().includes(filter.toLowerCase())))
  return <>
    <form className="panel upload" onSubmit={send}>
      <input type="file" ref={input} hidden multiple accept=".pdf,application/pdf" onChange={event => choose(Array.from(event.target.files ?? []))}/>
      <button type="button" className={'drop' + (drag ? ' dragging' : '')} disabled={percent !== undefined}
        onClick={() => input.current?.click()} onDragOver={event => { event.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)} onDrop={event => { event.preventDefault(); setDrag(false); if (percent === undefined) choose(Array.from(event.dataTransfer.files)) }}>
        <span className="empty-icon"><UploadCloud size={25}/></span><b>Drop PDFs here or browse files</b><small>Up to 10 reports per upload</small>
      </button>
      {!!selected.length && <><ul className="selected-files">{selected.map((file, i) => <li key={i}><FileText size={16}/>{file.name}</li>)}</ul>
        <div className="form-row"><label>Company override<input value={company} onChange={event => setCompany(event.target.value)} placeholder="Optional" maxLength={120}/></label>
          <label>Fiscal year override<input type="number" min={1900} max={2100} value={year} onChange={event => setYear(event.target.value)} placeholder="Optional"/></label>
          <button className="primary" disabled={percent !== undefined}>{percent === undefined ? 'Upload selected PDFs' : `Uploading ${percent}%`}</button></div></>}
    </form>
    {error && <p className="notice error" role="alert">{error}</p>}
    <section className="panel">
      <div className="panel-heading"><h2>Reports <small>{reports.length}</small></h2>
        <div className="filters"><label className="search"><Search size={16}/><input aria-label="Search reports" placeholder="Find a report" value={filter} onChange={event => setFilter(event.target.value)}/></label>
          <select aria-label="Processing status" value={state} onChange={event => setState(event.target.value)}><option value="">All statuses</option><option value="completed">Ready</option><option value="processing">Processing</option><option value="pending">Queued</option><option value="failed">Failed</option></select></div></div>
      {!visible.length ? <Empty title={reports.length ? 'No matching reports' : 'Your library is empty'} text={reports.length ? 'Try a different search or status.' : 'Upload your first report to make it available for research.'}/> :
        <div className="table-wrap"><table><thead><tr><th>Report</th><th>Fiscal year</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{visible.map(report => <tr key={report.id}>
            <td><button className="link" onClick={() => preview(report)}>{reportName(report)}</button><small>{report.filename} {report.page_count ? '· ' + report.page_count + ' pages' : ''}</small></td>
            <td>{report.year ?? '—'}</td>
            <td><StatePill report={report}/>{report.error && <small className="error-text">{report.error}</small>}
              {report.scan_pages.length > 0 && <small>{report.scan_pages.length} pages without extractable text</small>}
              {report.status === 'processing' && <><small>{report.stage}</small><progress value={report.progress} max={1}/></>}</td>
            <td><div className="actions"><button className="icon" disabled={acting === report.id || !['completed', 'failed'].includes(report.status)} title="Reprocess" aria-label={'Reprocess ' + report.filename} onClick={() => void change(report, false)}><RefreshCw size={17}/></button>
              <button className="icon" disabled={acting === report.id || !['completed', 'failed'].includes(report.status)} title="Delete" aria-label={'Delete ' + report.filename} onClick={() => setRemove(report)}><Trash2 size={17}/></button></div></td>
          </tr>)}</tbody></table></div>}
    </section>
    {remove && <div role="alertdialog" aria-modal="true" aria-label="Delete report" className="modal-shade"><div className="panel modal"><h2>Delete this report?</h2><p>{remove.filename} and its indexed evidence will be removed. Saved chat text will remain.</p>
      <div className="actions"><button className="outline" onClick={() => setRemove(undefined)}>Cancel</button><button className="danger" disabled={!!acting} onClick={() => void change(remove, true)}>Delete report</button></div></div></div>}
  </>
}

function Research({ mode, reports, session, open, clear, cite, refresh, status, goLibrary }: {
  mode: Mode; reports: Report[]; session?: Session; open: (session: Session) => void; clear: () => void
  cite: (citation: Citation) => void; refresh: () => Promise<void>; status?: Status; goLibrary: () => void
}) {
  const [ids, setIds] = useState<string[]>([])
  const [title, setTitle] = useState('')
  const [filter, setFilter] = useState('')
  const [editing, setEditing] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [messagesLoading, setMessagesLoading] = useState(false)
  const [error, setError] = useState('')
  const formEnd = useRef<HTMLDivElement>(null)
  const minimum = mode === 'single' ? 1 : 2
  const sessionId = session?.id
  useEffect(() => {
    setMessages([]); setError(''); setEditing(false)
    if (!sessionId) { setMessagesLoading(false); return }
    let active = true
    setMessagesLoading(true)
    api<Message[]>('/chat/sessions/' + sessionId + '/messages')
      .then(items => { if (active) setMessages(items) })
      .catch(err => { if (active) setError(err.message) })
      .finally(() => { if (active) setMessagesLoading(false) })
    return () => { active = false }
  }, [sessionId])
  async function save(event: FormEvent) {
    event.preventDefault()
    setBusy(true); setError('')
    try {
      const sessionTitle = title.trim() || (mode === 'single' ? reportName(reports.find(report => report.id === ids[0])!) : 'Financial research')
      open(await api<Session>('/chat/sessions' + (editing && session ? '/' + session.id : ''),
        json(editing ? 'PATCH' : 'POST', { title: sessionTitle, mode, document_ids: ids })))
      setEditing(false)
      await refresh()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  async function ask(event: FormEvent) {
    event.preventDefault()
    if (!session || !question.trim()) return
    setBusy(true); setError('')
    try {
      const response = await api<{user: Message; assistant: Message}>('/chat/sessions/' + session.id + '/query', json('POST', { question }))
      setMessages(items => [...items, response.user, response.assistant])
      setQuestion('')
      requestAnimationFrame(() => formEnd.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
      void refresh()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  const available = reports.filter(ready)
  const selected = available.filter(report => ids.includes(report.id))
  const filtered = available.filter(report => [report.filename, report.company_name, report.year].some(value => String(value ?? '').toLowerCase().includes(filter.toLowerCase())))
  const validSession = session?.document_ids.every(id => available.some(report => report.id === id))
  const examples = mode === 'single'
    ? ['What was the latest reported revenue?', 'Summarize the disclosed financial risks.']
    : ['Compare revenue growth across the selected companies.', 'Compare the disclosed financial risks.']

  return <>
    {error && <p className="notice error" role="alert">{error}</p>}
    {(!session || editing) && <section className="panel">
      <h2>{editing ? 'Edit session scope' : mode === 'single' ? 'Select a report' : 'Select research reports'}</h2>
      {available.length < minimum ? <Empty title="More indexed reports needed" text={mode === 'single' ? 'Upload a report to start a chat.' : 'Multi-document research requires at least two indexed reports.'}
        action={<button className="primary" onClick={goLibrary}>Open document library</button>}/> :
        <form className="session-form" onSubmit={save}>
          <div className="form-row"><label>Session name<input value={title} onChange={event => setTitle(event.target.value)} maxLength={160} placeholder="Optional"/></label>
            <label>Filter reports<input value={filter} onChange={event => setFilter(event.target.value)} placeholder="Company or fiscal year"/></label></div>
          <fieldset><legend>{selected.length} selected</legend>
            {filtered.map(report => <label className="choice" key={report.id}>
              <input type={mode === 'single' ? 'radio' : 'checkbox'} name="report" checked={ids.includes(report.id)}
                onChange={() => setIds(mode === 'single' ? [report.id] : ids.includes(report.id) ? ids.filter(id => id !== report.id) : [...ids, report.id])}/>
              <span><b>{reportName(report)}</b><small>{report.filename} {report.year ? '· FY' + report.year : ''}</small></span>
            </label>)}
            {!filtered.length && <p>No reports match this filter.</p>}
          </fieldset>
          <div className="actions"><button className="primary" disabled={busy || selected.length < minimum || selected.length > 30}>{editing ? 'Save selection' : 'Start session'} <ArrowRight size={17}/></button>
            {editing && <button type="button" className="outline" onClick={() => setEditing(false)}>Cancel</button>}</div>
        </form>}
    </section>}
    {session && !editing && <section className="panel chat">
      <div className="panel-heading"><h2>{session.title}</h2><div className="actions">
        <button className="outline" disabled={busy} onClick={() => { setIds(session.document_ids); setTitle(session.title); setEditing(true) }}>Edit scope</button>
        <button className="outline" disabled={busy} onClick={() => { setQuestion(''); setIds([]); setTitle(''); clear() }}>New session</button>
      </div></div>
      <div className="scope" aria-label="Selected reports">{session.document_ids.map(id => <span key={id}>
        <FileText size={14}/>{reports.find(report => report.id === id)?.filename ?? 'Removed report'}</span>)}</div>
      {!validSession && <p className="notice">Update the scope to continue with ready reports.</p>}
      {messagesLoading && <p className="notice" role="status">Loading conversation…</p>}
      {!messagesLoading && !messages.length && <div className="empty suggestions"><span className="empty-icon"><CircleHelp size={24}/></span>
        <h3>Ask your first question</h3><p>Try a question about the selected reports.</p>
        {examples.map(example => <button key={example} className="outline" onClick={() => setQuestion(example)}>{example}</button>)}</div>}
      <div className="messages" aria-live="polite">{messages.map(message => <article key={message.id} className={'message ' + message.role}>
        <b>{message.role === 'user' ? 'You' : 'FinSight AI'}</b>
        <p>{message.content}</p>
        {message.details.missing_information?.map(item => <small key={item}>{item}</small>)}
        {message.details.limitations?.map(item => <small key={item}>{item}</small>)}
        {!!message.details.citations?.length && <div className="citations">{message.details.citations.map(item =>
          <button key={item.id} onClick={() => cite(item)}><FileText size={14}/>{item.document_name} · p. {item.page}</button>)}</div>}
        {!!message.details.calculations?.length && <div className="calculations">{message.details.calculations.map((calc, i) => <details key={i}>
          <summary>{label(calc.operation)} · {calc.result} {calc.unit}</summary><p>{calc.formula}</p>
          {calc.inputs.map((input, index) => <button key={input.id + index} className="link" onClick={() => cite(input.citation)}>
            FY{input.year} · {input.label} · {amount(input)} ↗
          </button>)}
        </details>)}</div>}
      </article>)}{busy && <p className="notice" role="status">Checking report evidence…</p>}<div ref={formEnd}/></div>
      <form className="composer" onSubmit={ask}><label className="sr-only" htmlFor="question">Question</label>
        <textarea id="question" value={question} onChange={event => setQuestion(event.target.value)} maxLength={3000} placeholder="Ask about the selected reports…" rows={2}/>
        <button className="primary" aria-label="Send question" disabled={busy || messagesLoading || !question.trim() || !validSession}><ArrowUp size={20}/></button>
      </form>
      <p className="privacy">{status?.provider === 'mock' ? 'Mock provider mode uses local excerpts.' : 'Selected excerpts may be sent to Groq for answer generation.'}</p>
    </section>}
  </>
}

function HistoryList({ sessions, reports, open, refresh }: { sessions: Session[]; reports: Report[]; open: (session: Session) => void; refresh: () => Promise<void> }) {
  const [selected, setSelected] = useState<Session>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function remove() {
    if (!selected) return
    setBusy(true); setError('')
    try { await api('/chat/sessions/' + selected.id, { method: 'DELETE' }); setSelected(undefined); await refresh() }
    catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  return <section className="panel">
    {error && <p role="alert" className="notice error">{error}</p>}
    {!sessions.length ? <Empty title="No research history" text="Your document chats and research sessions will appear here."/> :
      <div className="table-wrap"><table><thead><tr><th>Session</th><th>Scope</th><th>Last updated</th><th>Actions</th></tr></thead>
        <tbody>{sessions.map(session => <tr key={session.id}>
          <td><button className="link" onClick={() => open(session)}>{session.title}</button><small>{session.mode === 'single' ? 'Document chat' : 'Multi-document research'}</small></td>
          <td>{session.document_ids.map(id => reports.find(report => report.id === id)?.filename ?? 'Removed report').join(', ')}</td>
          <td>{date(session.updated_at)}</td><td><button className="icon" title="Delete session" aria-label={'Delete ' + session.title} onClick={() => setSelected(session)}><Trash2 size={17}/></button></td>
        </tr>)}</tbody>
      </table></div>}
    {selected && <div className="modal-shade" role="alertdialog" aria-modal="true" aria-label="Delete session"><div className="panel modal"><h2>Delete this session?</h2><p>The conversation “{selected.title}” will be removed.</p>
      <div className="actions"><button className="outline" disabled={busy} onClick={() => setSelected(undefined)}>Cancel</button><button className="danger" disabled={busy} onClick={() => void remove()}>Delete session</button></div></div></div>}
  </section>
}
