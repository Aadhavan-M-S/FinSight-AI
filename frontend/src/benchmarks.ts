export type Split = { id: string; label: string; bytes?: number | null }
export type Installation = {
  split: string; revision: string; record_count: number; bytes: number; installed_at: string
  artifacts: { sha256: string; bytes: number; source_url?: string }[]
}
export type Dataset = {
  id: string; name: string; description: string; task_type: string; source: string; citation: string
  terms: string; terms_url: string; revision: string | null; splits: Split[]; tasks: Record<string, string>
  limitations: string; download_limit_bytes: number; download_mode: 'hub' | 'publisher' | 'import'
  import_url: string; noncommercial: boolean; state: string; installations: Installation[]
  job: { state: string; split: string; progress: number; message: string | null; downloaded: number; expected: number | null } | null
}
export type Passage = { id: string; text: string; kind: string; document: string | null; page_index: number | null }
export type Sample = { question_id: string; question: string; has_answer: boolean; answer_type: string | null }
export type BenchmarkRecord = Sample & {
  dataset_id: string; split: string; gold_answer: unknown; evidence: Passage[]; context: Passage[]; tables: unknown[]
  source: { filings?: { id: string; pdf_url: string; doc_link?: string }[] } & Record<string, unknown>
  program: unknown; previous_questions: string[]; relevant_ids: string[]; metadata: Record<string, unknown>
}
export type Finding = {
  question_id: string; question: string; state: string; gold_answer: unknown; prediction: unknown
  retrieved: Passage[]; attributed_ids: string[]; relevant_ids: string[]; metrics: Record<string, number>
  error: string | null; error_category: string | null
}
export type Run = {
  id: string; dataset_id: string; split: string; revision: string; task: string; state: string
  config: Record<string, unknown>; target: number; attempted: number; completed: number; failed: number
  unscored: number; unanswered: number; metrics: Record<string, number>; metric_counts: Record<string, number>
  started_at: string; finished_at: string | null; error: string | null; cancel_requested: number
}
export type Page<T> = { items: T[]; total: number }

export const installing = (state: string) => ['downloading', 'processing'].includes(state)
export const running = (state: string) => ['queued', 'running'].includes(state)
export const title = (value: string) => value.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase())
export const storage = (bytes: number) => (bytes / (1024 * 1024)).toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' MiB'
export const score = (value: number) => new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1 }).format(value)
export const show = (value: unknown) => value == null ? 'Unavailable' : typeof value === 'string' ? value : JSON.stringify(value, null, 2)
