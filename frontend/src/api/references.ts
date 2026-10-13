// Alternative views cite the primary chart's rows by JSON reference rather than repeating their
// citations ({"$ref": "#/visualization/data/3/citations"}); this puts the citations back.

import type { Citations, NetworkData, Row, Selection, View, VisualizationResponse } from './types'

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

/** What a written answer's ref points at, as the citation panel shows it; null when it has no
 * trials to show (e.g. a cohort's totals). */
export function selectionAt(response: VisualizationResponse, pointer: string): Selection | null {
  const viz = response.visualization
  const network = /^#\/visualization\/data\/(nodes|edges)\/(\d+)$/.exec(pointer)
  if (network && !Array.isArray(viz.data)) {
    const { nodes, edges } = viz.data as NetworkData
    if (network[1] === 'nodes') {
      const node = nodes[Number(network[2])]
      return node && { label: node.label, count: node.trial_count, citations: node.citations }
    }
    const edge = edges[Number(network[2])]
    const label = (id: string) => nodes.find((n) => n.id === id)?.label ?? id
    return edge && { label: `${label(edge.source)} — ${label(edge.target)}`, count: edge.trial_count, citations: edge.citations }
  }
  const row = /^#\/visualization\/data\/(\d+)$/.exec(pointer)
  if (row && Array.isArray(viz.data)) {
    const datum = (viz.data as Row[])[Number(row[1])]
    if (!datum) return null
    const named = Object.values(viz.encoding).filter((c) => c.type !== 'quantitative').map((c) => datum[c.field])
    const label = [...new Set(named)].filter((p) => p != null && p !== '').join(' · ') || String(datum._range ?? '')
    return {
      label,
      count: Number(datum.trial_count ?? datum.citations.total),
      citations: datum.citations,
      cohort: typeof datum.cohort === 'string' ? datum.cohort : undefined,
    }
  }
  const note = /^#\/meta\/note_citations\/(\d+)\/citations$/.exec(pointer)
  if (note) {
    const cited = response.meta.note_citations[Number(note[1])]
    return cited ? { label: cited.note, count: cited.citations.total, citations: cited.citations } : null
  }
  return null
}
