import { useState, type FormEvent } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, amount, json, label, type Citation, type Comparison as Result, type Report } from './api'

const metrics = ['revenue', 'net_profit', 'operating_profit', 'gross_profit', 'ebitda', 'assets', 'liabilities',
  'operating_cash_flow', 'capital_expenditure', 'operating_expenses', 'operating_margin', 'net_profit_margin',
  'gross_margin', 'earnings_per_share']
const colors = ['#226651', '#80633c', '#396890', '#a75c70', '#597d40']

export default function Comparison({ reports, cite }: { reports: Report[]; cite: (source: Citation) => void }) {
  const [metric, setMetric] = useState('revenue')
  const [company, setCompany] = useState('')
  const [years, setYears] = useState('')
  const [result, setResult] = useState<Result>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const ready = reports.filter(report => report.status === 'completed')
  const companies = new Map(ready.filter(report => report.company_id).map(report => [report.company_id!, report.company_name]))
  const filtered = company ? ready.filter(report => report.company_id === company) : ready
  async function run(event: FormEvent) {
    event.preventDefault()
    setError('')
    setResult(undefined)
    const selectedYears = years.split(',').map(item => item.trim()).filter(Boolean)
    if (selectedYears.some(item => !/^\d{4}$/.test(item))) { setError('Enter four-digit years separated by commas.'); return }
    setBusy(true)
    try {
      setResult(await api<Result>('/financials/compare', json('POST', {
        document_ids: filtered.map(report => report.id), company_ids: company ? [company] : [],
        years: selectedYears.map(Number), metric,
      })))
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  const names = Array.from(new Set(result?.facts.map(fact => fact.company || fact.citation.document_name)))
  const points = new Map<number, Record<string, string | number>>()
  for (const fact of result?.facts ?? []) {
    const row = points.get(fact.year) ?? { period: 'FY' + fact.year }
    row[fact.company || fact.citation.document_name] = Number(fact.normalized_value)
    points.set(fact.year, row)
  }
  const rows = Array.from(points).sort(([a], [b]) => a - b).map(([, row]) => row)
  return <>
    <form className="panel form-row" onSubmit={run}>
      <label>Company<select value={company} onChange={event => setCompany(event.target.value)}>
        <option value="">All indexed companies</option>{Array.from(companies).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select></label>
      <label>Metric<select value={metric} onChange={event => setMetric(event.target.value)}>
        {metrics.map(item => <option key={item} value={item}>{label(item)}</option>)}
      </select></label>
      <label>Fiscal years<input value={years} onChange={event => setYears(event.target.value)} placeholder="All years" /></label>
      <button className="primary" disabled={busy || !filtered.length}>{busy ? 'Comparing…' : 'Compare'}</button>
    </form>
    {!filtered.length && <p className="notice">Upload a financial report to start comparing figures.</p>}
    {error && <p role="alert" className="notice error">{error}</p>}
    {result && <section className="panel">
      <h2>Reported figures</h2>
      {result.facts.length === 0 && result.calculations.length === 0 && <p>No comparable source figures were found.</p>}
      {result.issues.map(issue => <p key={issue} className="notice">{issue}</p>)}
      {!!result.facts.length && !result.chart_compatible && <p className="notice">A shared chart requires compatible units, currencies, periods, and reporting bases.</p>}
      {result.chart_compatible && <div className="chart">
        <ResponsiveContainer width="100%" height={265}><LineChart data={rows}>
          <CartesianGrid stroke="#e9e9e1" vertical={false} /><XAxis dataKey="period" />
          <YAxis width={66} tickFormatter={value => Intl.NumberFormat(undefined, { notation: 'compact' }).format(value)} />
          <Tooltip /><Legend />
          {names.map((name, i) => <Line key={name} dataKey={name} stroke={colors[i % colors.length]} strokeWidth={2} />)}
        </LineChart></ResponsiveContainer>
      </div>}
      {!!result.facts.length && <div className="table-wrap"><table>
        <thead><tr><th>Company</th><th>Period</th><th>Reported value</th><th>Basis</th><th>Source</th></tr></thead>
        <tbody>{result.facts.map(fact => <tr key={fact.id}><td>{fact.company || fact.citation.document_name}</td>
          <td>FY{fact.year} · {fact.period}</td><td>{amount(fact)}</td><td>{fact.basis}</td>
          <td><button className="link" onClick={() => cite(fact.citation)}>Page {fact.citation.page} ↗</button></td>
        </tr>)}</tbody>
      </table></div>}
      {!!result.calculations.length && <><h3>Calculations</h3><ul className="calculations">
        {result.calculations.map(calc => <li key={calc.inputs.map(fact => fact.id).join('-')}>
          <b>{calc.inputs[0].company} · {calc.inputs[0].year === calc.inputs[1].year
            ? 'FY' + calc.inputs[0].year : 'FY' + calc.inputs[1].year + '–FY' + calc.inputs[0].year}
            {' · '}{label(calc.operation)} · {calc.result} {calc.unit}</b>
          <span>{calc.formula}</span>
          {calc.inputs.map(fact => <button key={fact.id} className="link" onClick={() => cite(fact.citation)}>FY{fact.year} · {amount(fact)} ↗</button>)}
        </li>)}
      </ul></>}
    </section>}
  </>
}
