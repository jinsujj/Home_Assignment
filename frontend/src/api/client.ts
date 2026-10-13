import type { VisualizationResponse } from './types'

export class ApiError extends Error {}

/** POST /api/visualize: a question plus optional structured fields. */
export const askQuestion = (request: unknown, signal?: AbortSignal) => post('/api/visualize', request, signal)

/** POST /api/plans: a structured analysis plan, no LLM involved. */
export const runPlan = (request: unknown, signal?: AbortSignal) => post('/api/plans', request, signal)

async function post(path: string, request: unknown, signal?: AbortSignal): Promise<VisualizationResponse> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (response.ok) return response.json()
  throw new ApiError(await describeError(response))
}

async function describeError(response: Response): Promise<string> {
  const body = await response.json().catch(() => null)
  const detail = body?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: [...], msg: "..."}]
    return detail.map((d) => `${d.loc?.slice(1).join('.')}: ${d.msg}`).join('\n')
  }
  if (detail?.message) {
    // Planning errors: {code, message, interpretation?, problems?}
    const lines = [detail.message]
    if (detail.interpretation) lines.push(`Understood as: ${detail.interpretation}`)
    if (detail.problems) lines.push(...detail.problems.map((p: string) => `• ${p}`))
    return lines.join('\n')
  }
  return `${response.status} ${response.statusText}`
}
