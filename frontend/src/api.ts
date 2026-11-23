export type Report = {
  id: string; filename: string; company_id: string | null; company_name: string | null
  year: number | null; status: 'pending' | 'processing' | 'completed' | 'failed'
  error: string | null; progress: number; stage: string | null; page_count: number; scan_pages: number[]
  created_at: string
}
export type Mode = 'single' | 'research'
export type Session = { id: string; title: string; mode: Mode; document_ids: string[]; updated_at: string }
export type Citation = {
  id: string; document_id: string; document_name: string; page: number; printed_page: string | null
  section: string; text: string; boxes: number[][]; page_size: [number, number] | null
}
export type Fact = {
  id: string; company_id: string | null; company: string | null; year: number
  metric: string; label: string; value: string; normalized_value: string
  currency: string | null; unit: string; period: string; basis: string; citation: Citation
}
export type Calculation = { operation: string; result: string; unit: string; formula: string; inputs: Fact[] }
export type Details = {
  answer_status: string; answer_type: string; citations: Citation[]; calculations: Calculation[]
  limitations: string[]; missing_information: string[]; provider: string
}
export type Message = { id: string; role: 'user' | 'assistant'; content: string; details: Partial<Details> }
export type Status = { provider: string; dense_retrieval: boolean; groq_key_configured: boolean }
export type Comparison = { facts: Fact[]; calculations: Calculation[]; issues: string[]; chart_compatible: boolean }
export type UploadResult = { documents: Report[]; errors: { filename: string; message: string }[] }

export const apiRoot = '/api/v1'
export function failure(body: { detail?: unknown }, status: number) {
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) return body.detail.map(item => item.msg).join(' ')
  return 'Request failed (' + status + ').'
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiRoot + path, init)
  if (!response.ok) throw new Error(failure(await response.json().catch(() => ({})), response.status))
  return response.status === 204 ? undefined as T : response.json()
}

export function json(method: string, data: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }
}

export function upload(form: FormData, onProgress: (percentage: number) => void) {
  return new Promise<UploadResult>((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', apiRoot + '/documents/upload')
    request.responseType = 'json'
    request.timeout = 180000
    request.upload.onprogress = event => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100))
    }
    request.onload = () => {
      if (request.status === 202) resolve(request.response)
      else reject(new Error(failure(request.response ?? {}, request.status)))
    }
    request.onerror = () => reject(new Error('The upload connection failed.'))
    request.ontimeout = () => reject(new Error('The upload timed out.'))
    request.send(form)
  })
}

export const date = (value: string) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value))
export const label = (value: string) => value.replaceAll('_', ' ')
export const amount = (fact: Fact) => {
  const value = fact.currency ? fact.normalized_value : fact.value
  const [integer, decimal] = value.split('.')
  const display = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (decimal ? '.' + decimal : '')
  return display + (fact.currency ? ' ' + fact.currency : fact.unit === 'percent' ? '%' : ' source units')
}
