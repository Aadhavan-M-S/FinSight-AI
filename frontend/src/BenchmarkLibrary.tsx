import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ArrowLeft, ChevronRight, Database, Download, FileChartColumn, FlaskConical, Plus, Search } from 'lucide-react'
import { api, apiRoot, json } from './api'
import {
  installing, running, score, show, storage, title,
  type BenchmarkRecord, type Dataset, type Finding, type Page, type Passage, type Run, type Sample, type Split,
} from './benchmarks'
import './benchmark.css'

const PAGE_SIZE = 15
const collection = '/benchmarks'
const evaluations = '/evaluations'

function Badge({ state }: { state: string }) {
  return <span className={'pill ' + (state === 'ready' || state === 'completed' || state === 'scored' ? 'completed' : state === 'failed' ? 'failed' : '')}>{title(state)}</span>
}

function ErrorNotice({ message }: { message: string }) {
  return message ? <p className="notice error" role="alert">{message}</p> : null
}

function Pages({ offset, total, change }: { offset: number; total: number; change: (value: number) => void }) {
  if (!total) return null
  return <div className="benchmark-pages">
    <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}</span>
    <div className="actions">
      <button className="outline" disabled={offset === 0} onClick={() => change(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
      <button className="outline" disabled={offset + PAGE_SIZE >= total} onClick={() => change(offset + PAGE_SIZE)}>Next</button>
    </div>
  </div>
}

export default function BenchmarkLibrary({ groqConfigured }: { groqConfigured: boolean }) {
  const [view, setView] = useState<'library' | 'runs'>('library')
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [selected, setSelected] = useState('')
  const [selectedRun, setSelectedRun] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const [items, recent] = await Promise.all([api<Dataset[]>(collection), api<Run[]>(evaluations)])
      setDatasets(items)
      setRuns(recent)
      setError('')
    } catch (err) { setError((err as Error).message) } finally { setLoading(false) }
  }, [])

  const working = datasets.some(item => installing(item.state)) || runs.some(item => running(item.state))
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!working) return
    const interval = setInterval(() => void refresh(), 1300)
    return () => clearInterval(interval)
  }, [working, refresh])
  const dataset = datasets.find(item => item.id === selected)
  const run = runs.find(item => item.id === selectedRun)

  function openRun(runId: string) {
    setSelectedRun(runId)
    setView('runs')
    void refresh()
  }

  return <div className="benchmark">
    <div className="benchmark-tabs" aria-label="Benchmark workspace">
      <button className="outline" aria-pressed={view === 'library'} onClick={() => setView('library')}><Database size={16}/> Datasets</button>
      <button className="outline" aria-pressed={view === 'runs'} onClick={() => setView('runs')}><FileChartColumn size={16}/> Evaluation runs</button>
    </div>
    <ErrorNotice message={error}/>
    {loading && <p role="status" className="notice">Loading benchmark workspace…</p>}
    {view === 'library' && dataset && <DatasetPanel key={dataset.id} dataset={dataset}
      goBack={() => setSelected('')} refresh={refresh} openRun={openRun} groqConfigured={groqConfigured} />}
    {view === 'library' && !dataset && !loading && <div className="benchmark-grid">
      {datasets.map(item => <article className="panel benchmark-card" key={item.id}>
        <div className="panel-heading"><span className="tile-icon"><Database size={17}/></span><Badge state={item.state}/></div>
        <h2>{item.name}</h2><p>{item.description}</p>
        <dl className="benchmark-meta">
          <dt>Task</dt><dd>{item.task_type}</dd>
          <dt>Terms</dt><dd>{item.terms}</dd>
          <dt>Splits</dt><dd>{item.splits.map(split => split.id).join(', ') || 'Discover from publisher'}</dd>
          <dt>Download</dt><dd>{item.download_mode === 'import' ? 'Publisher file import' : 'On demand'} · up to {storage(item.download_limit_bytes)}</dd>
        </dl>
        <div className="benchmark-card-actions">
          <a className="link" href={item.source} target="_blank" rel="noreferrer">Official source ↗</a>
          <button className="outline" onClick={() => setSelected(item.id)}>View {item.name} <ChevronRight size={16}/></button>
        </div>
      </article>)}
    </div>}
    {view === 'runs' && <div className="benchmark">
      <section className="panel">
        <h2>Saved evaluations</h2>
        {!runs.length && <p className="notice">Install a dataset with a supported task to start an evaluation.</p>}
        {!!runs.length && <div className="table-wrap"><table>
          <thead><tr><th>Dataset</th><th>Split</th><th>Task</th><th>Attempted</th><th>Status</th></tr></thead>
          <tbody>{runs.map(item => <tr key={item.id}>
            <td><button className="link" onClick={() => setSelectedRun(item.id)}>{datasets.find(d => d.id === item.dataset_id)?.name ?? item.dataset_id} ↗</button>
              <small>{new Date(item.started_at).toLocaleString()}</small></td>
            <td>{item.split}</td><td>{title(item.task)}</td><td>{item.attempted}/{item.target}</td><td><Badge state={item.state}/></td>
          </tr>)}</tbody>
        </table></div>}
      </section>
      {run && <RunPanel key={run.id} item={run} refresh={refresh} />}
    </div>}
  </div>
}

function DatasetPanel({ dataset, goBack, refresh, openRun, groqConfigured }: {
  dataset: Dataset; goBack: () => void; refresh: () => Promise<void>; openRun: (id: string) => void; groqConfigured: boolean
}) {
  const path = collection + '/' + dataset.id
  const [splits, setSplits] = useState<Split[]>(dataset.splits)
  const [license, setLicense] = useState('')
  const [publishedRevision, setPublishedRevision] = useState(dataset.revision)
  const [split, setSplit] = useState(dataset.installations[0]?.split ?? dataset.splits[0]?.id ?? '')
  const [accepted, setAccepted] = useState(false)
  const [manual, setManual] = useState(dataset.download_mode === 'import')
  const [file, setFile] = useState<File>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const installation = dataset.installations.find(item => item.split === split)
  const job = dataset.job
  const locked = busy || installing(dataset.state)
  const currentSplit = splits.find(item => item.id === split)

  async function action(call: () => Promise<void>) {
    setBusy(true); setError('')
    try { await call() } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  async function discover() {
    await action(async () => {
      const data = await api<{ splits: Split[]; license: string | null; revision: string }>(path + '/splits')
      setSplits(data.splits); setLicense(data.license ?? ''); setPublishedRevision(data.revision)
      if (!split) setSplit(data.splits[0]?.id ?? '')
    })
  }
  function install(event: FormEvent) {
    event.preventDefault()
    void action(async () => {
      if (manual) {
        if (!file) return
        const form = new FormData()
        form.append('file', file); form.append('split', split); form.append('accept_restrictions', String(accepted))
        await api(path + '/import', { method: 'POST', body: form })
      } else {
        await api(path + '/install', json('POST', { split, accept_restrictions: accepted }))
      }
      await refresh()
    })
  }
  async function remove() {
    await action(async () => {
      await api(path + '/installation?' + new URLSearchParams({ split }), { method: 'DELETE' })
      setConfirmRemove(false)
      await refresh()
    })
  }
  const choices = Array.from(new Map([
    ...dataset.installations.map(item => [item.split, { id: item.split, label: item.split }] as const),
    ...splits.map(item => [item.id, item] as const),
  ]).values())

  return <>
    <button className="link benchmark-back" onClick={goBack}><ArrowLeft size={16}/> All datasets</button>
    <section className="panel benchmark-detail">
      <div className="panel-heading"><div><h2>{dataset.name}</h2><p>{dataset.description}</p></div><Badge state={dataset.state}/></div>
      <dl className="benchmark-meta">
        <dt>Task</dt><dd>{dataset.task_type}</dd>
        <dt>License / terms</dt><dd>{license || dataset.terms} <a className="link" href={dataset.terms_url} target="_blank" rel="noreferrer">Review terms ↗</a></dd>
        <dt>Source</dt><dd><a className="link" href={dataset.source} target="_blank" rel="noreferrer">Publisher release ↗</a>{' · '}
          <a className="link" href={dataset.citation} target="_blank" rel="noreferrer">Research citation ↗</a></dd>
        <dt>Revision</dt><dd><code title={publishedRevision ?? ''}>{publishedRevision?.slice(0, 12) ?? 'Discovered from publisher'}</code></dd>
        <dt>Storage</dt><dd>Up to {storage(dataset.download_limit_bytes)} to download or import. Validation needs additional free space.</dd>
      </dl>
      <p className="notice">{dataset.limitations}</p>
      <ErrorNotice message={error}/>
      {dataset.download_mode === 'hub' && <button className="outline benchmark-back" disabled={locked} onClick={() => void discover()}>Discover official splits</button>}
      <form className="benchmark-form" onSubmit={install}>
        {choices.length > 0 && !(manual && dataset.download_mode === 'hub' && !splits.length) ?
          <label>Publisher split<select value={split} onChange={event => setSplit(event.target.value)}>
            <option value="">Choose split</option>{choices.map(item => <option key={item.id} value={item.id}>{item.label} ({item.id})</option>)}
          </select></label> :
          <label>Publisher split<input value={split} onChange={event => setSplit(event.target.value)} placeholder="Official split identifier" disabled={!manual}/></label>}
        {currentSplit?.bytes != null && <small>Publisher download size {storage(currentSplit.bytes)}</small>}
        {dataset.download_mode !== 'import' && <label className="choice"><input type="checkbox" checked={manual}
          onChange={event => setManual(event.target.checked)} disabled={locked}/> Import a publisher file</label>}
        {manual && <label>Official split file <a className="link" href={dataset.import_url} target="_blank" rel="noreferrer">Get it from the publisher ↗</a>
          <input type="file" accept=".json,.jsonl,.parquet" onChange={event => setFile(event.target.files?.[0])}/></label>}
        {dataset.noncommercial && <label className="choice"><input type="checkbox" checked={accepted} onChange={event => setAccepted(event.target.checked)}/>
          I will use this release for noncommercial purposes.</label>}
        <div className="actions">
          <button className="primary" disabled={locked || !split || (manual && !file) || (dataset.noncommercial && !accepted) ||
            (!manual && currentSplit?.bytes != null && currentSplit.bytes > dataset.download_limit_bytes)}>
            <Download size={16}/>{manual ? 'Import split' : installation ? 'Reinstall split' : 'Install split'}</button>
          {installation && <button type="button" className="outline" disabled={locked} onClick={() => setConfirmRemove(true)}>Remove split</button>}
        </div>
        {confirmRemove && <div className="notice" role="alert">
          Remove the locally installed {split} records? Saved evaluations remain available.
          <div className="actions">
            <button type="button" className="outline" onClick={() => setConfirmRemove(false)}>Keep split</button>
            <button type="button" className="danger" disabled={locked} onClick={() => void remove()}>Confirm removal</button>
          </div>
        </div>}
      </form>
      {job && (installing(job.state) || job.state === 'failed') && <div role={job.state === 'failed' ? 'alert' : 'status'}
        className={'notice ' + (job.state === 'failed' ? 'error' : '')}>
        <b>{job.split}</b> · {job.message ?? title(job.state)}
        {installing(job.state) && <><progress value={job.expected || job.state === 'processing' ? job.progress : undefined} max={1} />
          {job.downloaded > 0 && <small>{storage(job.downloaded)} {job.expected ? 'of ' + storage(job.expected) : 'downloaded'}</small>}</>}
      </div>}
      {installation && <p className="notice">{installation.record_count.toLocaleString()} records · {storage(installation.bytes)} source data · <code title={installation.revision}>{installation.revision.slice(0, 21)}</code></p>}
    </section>
    {installation && <RecordExplorer key={split + installation.installed_at} path={path} split={split}/>}
    {installation && Object.keys(dataset.tasks).length > 0 && <RunForm key={split} dataset={dataset} split={split} groqConfigured={groqConfigured} openRun={openRun}/>}
  </>
}

function RecordExplorer({ path, split }: { path: string; split: string }) {
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<Page<Sample>>()
  const [record, setRecord] = useState<BenchmarkRecord>()
  const [error, setError] = useState('')
  const [detailId, setDetailId] = useState('')

  useEffect(() => {
    let active = true
    setPage(undefined); setError('')
    const params = new URLSearchParams({ split, q: query, limit: String(PAGE_SIZE), offset: String(offset) })
    api<Page<Sample>>(path + '/samples?' + params).then(data => { if (active) setPage(data) })
      .catch(err => { if (active) setError(err.message) })
    return () => { active = false }
  }, [path, split, query, offset])
  useEffect(() => {
    let active = true
    setRecord(undefined)
    if (detailId) {
      api<BenchmarkRecord>(path + '/samples/' + encodeURIComponent(detailId) + '?' + new URLSearchParams({ split }))
        .then(data => { if (active) setRecord(data) }).catch(err => { if (active) setError(err.message) })
    }
    return () => { active = false }
  }, [detailId, path, split])

  return <section className="panel benchmark">
    <div className="panel-heading"><h2>Explore records</h2><small>{split}</small></div>
    <form className="form-row" onSubmit={event => { event.preventDefault(); setOffset(0); setDetailId(''); setQuery(search) }}>
      <label>Search questions<input value={search} onChange={event => setSearch(event.target.value)} maxLength={200}/></label>
      <button className="outline"><Search size={15}/> Search</button>
    </form>
    <ErrorNotice message={error}/>
    {!page && !error && <p role="status" className="notice">Loading records…</p>}
    {page && !page.total && <p className="notice">No questions match this search.</p>}
    {page && <><ul className="row-list">{page.items.map(item => <li key={item.question_id}>
      <button onClick={() => setDetailId(item.question_id)} aria-pressed={detailId === item.question_id}>
        <span className="row-label"><b>{item.question}</b><small>{item.question_id} · {item.has_answer ? item.answer_type ?? 'Reference available' : 'Reference unavailable'}</small></span>
        <ChevronRight size={16}/>
      </button>
    </li>)}</ul><Pages offset={offset} total={page.total} change={next => { setOffset(next); setDetailId('') }}/></>}
    {detailId && !record && !error && <p role="status" className="notice">Loading question…</p>}
    {record && <RecordDetail record={record} close={() => setDetailId('')}/>}
  </section>
}

function SourceTable({ value, index }: { value: unknown; index: number }) {
  if (!Array.isArray(value) && typeof value !== 'string') return <pre>{show(value)}</pre>
  const template = document.createElement('template')
  if (typeof value === 'string') template.innerHTML = value
  const source = template.content.querySelector('table')
  const rows = source ? Array.from(source.rows).slice(0, 100).map(row => Array.from(row.cells).map(cell => ({
    text: cell.textContent, col: Math.min(cell.colSpan, 30), row: Math.min(cell.rowSpan, 100),
  }))) : Array.isArray(value) ? value.slice(0, 100).map(row => Array.isArray(row) ?
    row.map(text => ({ text: String(text ?? ''), col: 1, row: 1 })) : []) : []
  if (!rows.length) return <pre>{show(value)}</pre>
  return <div className="table-wrap"><table><caption>Table {index + 1}</caption><tbody>{rows.map((row, i) => <tr key={i}>
    {row.map((cell, j) => <td key={j} colSpan={cell.col} rowSpan={cell.row}>{cell.text}</td>)}
  </tr>)}</tbody></table></div>
}

function Excerpt({ passage, url }: { passage: Passage; url?: string }) {
  return <article className="benchmark-excerpt">
    <b>{passage.id}</b>
    {passage.page_index != null && <small>PDF page {passage.page_index + 1} · publisher index {passage.page_index}</small>}
    {url && passage.page_index != null && <a className="link" href={url + '#page=' + (passage.page_index + 1)}
      target="_blank" rel="noreferrer">Open source page ↗</a>}
    <p>{passage.text}</p>
  </article>
}

function RecordDetail({ record, close }: { record: BenchmarkRecord; close: () => void }) {
  const { publisher, ...metadata } = record.metadata
  const pdfPath = (filing: string) => apiRoot + collection + '/' + record.dataset_id + '/filings/' +
    encodeURIComponent(filing) + '?' + new URLSearchParams({ split: record.split, question_id: record.question_id })
  return <article className="benchmark-record">
    <div className="panel-heading"><h3>{record.question}</h3><button className="outline" onClick={close}>Close question</button></div>
    {record.previous_questions.length > 0 && <details><summary>Earlier conversation questions</summary>
      <ol>{record.previous_questions.map((question, index) => <li key={index}>{question}</li>)}</ol></details>}
    <h4>Reference answer</h4><pre>{show(record.gold_answer)}</pre>
    {record.program != null && record.program !== '' && <details><summary>Reference reasoning program</summary><pre>{show(record.program)}</pre></details>}
    {!!record.evidence.length && <details open><summary>Annotated evidence ({record.evidence.length})</summary>
      {record.evidence.map((item, index) => <Excerpt key={item.id + index} passage={item}
        url={item.document && record.source.filings?.some(file => file.id === item.document) ? pdfPath(item.document) : undefined}/>)}
    </details>}
    {!!record.tables.length && <details><summary>Source tables ({record.tables.length})</summary>
      {record.tables.map((item, index) => <SourceTable key={index} value={item} index={index}/>)}
    </details>}
    {!!record.context.length && <details><summary>Source context ({record.context.length})</summary>
      <div className="benchmark-context">{record.context.map((item, index) => <Excerpt key={item.id + index} passage={item}/>)}</div>
    </details>}
    {record.source.filings?.map(item => <a key={item.id} className="link" href={pdfPath(item.id)}
      target="_blank" rel="noreferrer">{item.id} PDF ↗</a>)}
    <details><summary>Source metadata</summary><pre>{show(record.source)}</pre><pre>{show(metadata)}</pre></details>
    {publisher != null && <details><summary>Publisher record fields</summary><pre>{show(publisher)}</pre></details>}
  </article>
}

function RunForm({ dataset, split, groqConfigured, openRun }: { dataset: Dataset; split: string; groqConfigured: boolean; openRun: (id: string) => void }) {
  const [task, setTask] = useState(Object.keys(dataset.tasks)[0])
  const [limit, setLimit] = useState(5)
  const [topK, setTopK] = useState(5)
  const [retrieval, setRetrieval] = useState('bm25')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const hosted = task !== 'retrieval'
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const result = await api<Run>(evaluations + '/run', json('POST', {
        dataset_id: dataset.id, split, task, limit, top_k: topK, retrieval, provider: hosted ? 'groq' : null,
      }))
      openRun(result.id)
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  return <section className="panel benchmark">
    <div className="panel-heading"><h2>Run evaluation</h2><span className="tile-icon"><FlaskConical size={18}/></span></div>
    <form className="form-row" onSubmit={submit}>
      <label>Task<select value={task} onChange={event => {
        setTask(event.target.value); if (event.target.value !== 'retrieval') setLimit(Math.min(limit, 15))
      }}>{Object.entries(dataset.tasks).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>Retrieval<select value={retrieval} onChange={event => setRetrieval(event.target.value)}>
        <option value="bm25">BM25</option><option value="hybrid">Hybrid with reranking</option>
      </select></label>
      <label>Questions<input type="number" min={1} max={hosted ? 15 : 100} required value={limit} onChange={event => setLimit(Number(event.target.value))}/></label>
      <label>Top K<input type="number" min={1} max={20} required value={topK} onChange={event => setTopK(Number(event.target.value))}/></label>
      <button className="primary" disabled={busy || (hosted && !groqConfigured)}><Plus size={16}/> Start run</button>
    </form>
    {hosted && <p className="notice">{groqConfigured ? 'Groq receives the selected source excerpts and questions. Each run is limited to 15 questions.'
      : 'Set GROQ_API_KEY in your local environment to run this task.'}</p>}
    <ErrorNotice message={error}/>
  </section>
}

function RunPanel({ item, refresh }: { item: Run; refresh: () => Promise<void> }) {
  const path = evaluations + '/' + item.id
  const [page, setPage] = useState<Page<Finding>>()
  const [offset, setOffset] = useState(0)
  const [state, setState] = useState('')
  const [error, setError] = useState('')
  const active = running(item.state)
  useEffect(() => {
    let present = true
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) })
    if (state) params.set('state', state)
    api<Page<Finding>>(path + '/results?' + params).then(data => { if (present) setPage(data) })
      .catch(err => { if (present) setError(err.message) })
    return () => { present = false }
  }, [path, offset, state, item.attempted, item.state])
  async function cancel() {
    try { await api(path + '/cancel', { method: 'POST' }); await refresh() }
    catch (err) { setError((err as Error).message) }
  }
  return <section className="panel benchmark">
    <div className="panel-heading"><h2>Evaluation results</h2><Badge state={item.state}/></div>
    <p>{item.dataset_id} · {item.split} · {title(String(item.config.protocol))}</p>
    <div className="benchmark-counts">
      <span><b>{item.attempted}/{item.target}</b> Attempted</span><span><b>{item.completed}</b> Completed</span>
      <span><b>{item.failed}</b> Failed</span><span><b>{item.unanswered}</b> Unanswered</span><span><b>{item.unscored}</b> Unscored</span>
    </div>
    {active && <progress value={item.attempted} max={item.target}/>}
    <ErrorNotice message={error || item.error || ''}/>
    {Object.keys(item.metrics).length > 0 ? <dl className="benchmark-meta">
      {Object.entries(item.metrics).map(([name, value]) => <div className="benchmark-metric" key={name}>
        <dt>{title(name)}</dt><dd><b>{score(value)}</b> · {item.metric_counts[name]} eligible records</dd>
      </div>)}
    </dl> : <p className="notice">No measures have been recorded for this run.</p>}
    <details><summary>Run configuration</summary><pre>{show(item.config)}</pre></details>
    <div className="actions">
      {active ? <button className="outline" disabled={!!item.cancel_requested} onClick={() => void cancel()}>{item.cancel_requested ? 'Cancelling…' : 'Cancel run'}</button> :
        <><a className="outline" href={apiRoot + path + '/export?format=json'}>Export JSON</a>
          <a className="outline" href={apiRoot + path + '/export?format=csv'}>Export CSV</a></>}
    </div>
    <label className="benchmark-filter">Result status<select value={state} onChange={event => { setOffset(0); setState(event.target.value) }}>
      <option value="">All results</option>{['failed', 'unanswered', 'unscored', 'scored'].map(value => <option key={value} value={value}>{title(value)}</option>)}
    </select></label>
    {page && !page.total && <p className="notice">No results for this view.</p>}
    {page && <><div className="benchmark">
      {page.items.map(finding => <details key={finding.question_id} className="benchmark-record">
        <summary>{finding.question} <Badge state={finding.state}/></summary>
        {finding.error && <p className="notice error">{title(finding.error_category ?? 'Error')} · {finding.error}</p>}
        <div className="overview-grid"><div><h4>Prediction</h4><pre>{show(finding.prediction)}</pre></div>
          <div><h4>Reference answer</h4><pre>{show(finding.gold_answer)}</pre></div></div>
        <p>Annotated evidence IDs {finding.relevant_ids.join(', ') || 'unavailable'}</p>
        <p>Attributed IDs {finding.attributed_ids.join(', ') || 'unavailable'}</p>
        {!!Object.keys(finding.metrics).length && <pre>{show(finding.metrics)}</pre>}
        {finding.retrieved.map(passage => <Excerpt key={passage.id} passage={passage}/>)}
      </details>)}
    </div><Pages offset={offset} total={page.total} change={setOffset}/></>}
  </section>
}
