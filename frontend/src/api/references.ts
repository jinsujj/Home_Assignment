// Alternative views cite the primary chart's rows by JSON reference rather than repeating their
// citations ({"$ref": "#/visualization/data/3/citations"}); this puts the citations back.

import type { Citations, NetworkData, View, VisualizationResponse } from './types'

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

/** Where each citations object sits in the response, as a JSON pointer like the references';
 * the same answer fetched again keeps them there. */
export function citationPointers(response: VisualizationResponse): Map<Citations, string> {
  const found = new Map<Citations, string>()
  const rows = (list: { citations?: Citations | { $ref: string } }[], at: string) =>
    list.forEach((row, i) => {
      if (row.citations && !('$ref' in row.citations)) found.set(row.citations, `${at}/${i}/citations`)
    })
  const data = (data: Data, at: string) =>
    Array.isArray(data) ? rows(data, at) : (rows(data.nodes, `${at}/nodes`), rows(data.edges, `${at}/edges`))
  data(response.visualization.data, '#/visualization/data')
  response.alternatives.forEach((view, i) => data(view.data, `#/alternatives/${i}/data`))
  response.meta.note_citations.forEach((note, i) => found.set(note.citations, `#/meta/note_citations/${i}/citations`))
  return found
}

/** The citations at `pointer`, following a reference to the primary chart's. */
export function citationsAt(response: VisualizationResponse, pointer: string): Citations | undefined {
  const found = lookup(response, pointer) as Citations | { $ref: string } | undefined
  return found && '$ref' in found ? (lookup(response, found.$ref) as Citations) : found
}
