import type { MentionVerdict, SearchOptions, VisualizationResponse } from './types'

/** `code` is set for answers that explain why there is no chart (refusals, unknown trials). */
export class ApiError extends Error {
  readonly code?: string

  constructor(message: string, code?: string) {
    super(message)
    this.code = code
  }
}

const EXPLAINED = new Set(['unsupported_question', 'no_posted_results', 'trial_not_found'])

/** POST /api/visualize: a question plus optional structured fields. */
export const askQuestion = (request: unknown, signal?: AbortSignal) => post('/api/visualize', request, signal)

/** POST /api/plans: a structured analysis plan, no LLM involved. */
export const runPlan = (request: unknown, signal?: AbortSignal) => post('/api/plans', request, signal)

/** GET /api/options: registry countries, common terms, phase and status codes. */
export async function getOptions(signal?: AbortSignal): Promise<SearchOptions> {
  const response = await fetch('/api/options', { signal })
  if (response.ok) return response.json()
  const [message] = await describeError(response)
  throw new ApiError(message)
}

/** POST /api/mentions: a language model judges why trials mention the filtered entity. */
export async function judgeMentions(nctIds: string[], names: string[], signal?: AbortSignal): Promise<MentionVerdict[]> {
  const response = await fetch('/api/mentions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nct_ids: nctIds, names }),
    signal,
  })
  if (response.ok) return (await response.json()).verdicts
  const [message] = await describeError(response)
  throw new ApiError(message)
}

/** GET /api/version: the registry data snapshot being served (null when unknown). */
export async function getVersion(signal?: AbortSignal): Promise<string | null> {
  const response = await fetch('/api/version', { signal })
  if (!response.ok) throw new ApiError(`${response.status} ${response.statusText}`)
  return (await response.json()).data_version
}

async function post(path: string, request: unknown, signal?: AbortSignal): Promise<VisualizationResponse> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (response.ok) return response.json()
  const [message, code] = await describeError(response)
  throw new ApiError(message, code && EXPLAINED.has(code) ? code : undefined)
}

async function describeError(response: Response): Promise<[string, string?]> {
  const body = await response.json().catch(() => null)
  const detail = body?.detail
  if (typeof detail === 'string') return [detail]
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: [...], msg: "..."}]
    return [detail.map((d) => `${d.loc?.slice(1).join('.')}: ${d.msg}`).join('\n')]
  }
  if (detail?.message) {
    // {code, message, problems?, trial?}
    const lines = [detail.message]
    if (detail.problems) lines.push(...detail.problems.map((p: string) => `• ${p}`))
    if (detail.trial?.url) lines.push(`Trial record: ${detail.trial.url}`)
    return [lines.join('\n'), detail.code]
  }
  return [`${response.status} ${response.statusText}`]
}
