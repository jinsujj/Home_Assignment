import type { VisualizationResponse } from './types'

export class ApiError extends Error {}

export async function runPlan(request: unknown, signal?: AbortSignal): Promise<VisualizationResponse> {
  const response = await fetch('/api/plans', {
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
  return `${response.status} ${response.statusText}`
}
