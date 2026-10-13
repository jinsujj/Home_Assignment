// Alternative views cite the primary chart's rows by JSON reference rather than repeating their
// citations ({"$ref": "#/visualization/data/3/citations"}); this puts the citations back.

import type { NetworkData, View, VisualizationResponse } from './types'

type Data = View['data']

function lookup(response: VisualizationResponse, ref: string): unknown {
  return ref
    .replace(/^#\//, '')
    .split('/')
    .reduce<unknown>((node, key) => (node as Record<string, unknown> | undefined)?.[key], response)
}

function resolveRows<T extends object>(rows: T[], response: VisualizationResponse): T[] {
  return rows.map((row) => {
    const ref = (row as { citations?: { $ref?: string } }).citations?.$ref
    return ref ? { ...row, citations: lookup(response, ref) } : row
  })
}

/** The response's alternative views with every citation reference resolved. */
export function resolvedViews(response: VisualizationResponse): View[] {
  return response.alternatives.map((view) => {
    const data: Data = Array.isArray(view.data)
      ? resolveRows(view.data, response)
      : { nodes: resolveRows((view.data as NetworkData).nodes, response), edges: resolveRows((view.data as NetworkData).edges, response) }
    return { ...view, data }
  })
}
