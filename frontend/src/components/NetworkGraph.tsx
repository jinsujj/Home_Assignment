import cytoscape from 'cytoscape'
import { useEffect, useRef } from 'react'
import type { NetworkData, Selection, Visualization } from '../api/types'

// Colour = cluster (node_color), shape = entity kind (node_shape), dark = anchor, border =
// sponsor class (node_category); edge width = shared trials (edge_weight), opacity = association
// (edge_strength), line style = how the two meet (edge_style).
const PALETTE = ['#2f6fdd', '#e0782f', '#2a9d6f', '#9b5de5', '#d64550', '#c9a227', '#1fa3b8', '#8a6d3b']
const NO_CLUSTER = '#b8c0c8'
const ANCHOR = '#1d2228'
const SHAPES = ['ellipse', 'round-rectangle'] as const
const LINE: Record<string, { style: 'solid' | 'dashed' | 'dotted'; legend: string }> = {
  combined: { style: 'solid', legend: 'combined in one arm' },
  compared: { style: 'dashed', legend: 'only in different arms (compared)' },
  unknown: { style: 'dotted', legend: 'arms do not say' },
  lead: { style: 'solid', legend: 'sponsor leads' },
  collaborator: { style: 'dashed', legend: 'sponsor collaborates' },
}
const SPONSOR_CLASS: Record<string, { color: string; legend: string }> = {
  INDUSTRY: { color: '#b45309', legend: 'industry' },
  NIH: { color: '#15803d', legend: 'NIH' },
  OTHER_GOV: { color: '#0e7490', legend: 'other government' },
  FED: { color: '#0e7490', legend: 'US federal' },
  OTHER: { color: '#6b7280', legend: 'university, hospital, other' },
}
const OTHER_CLASS = { color: '#a1a1aa', legend: 'other' }

interface Props {
  visualization: Visualization
  onSelect: (selection: Selection) => void
}

/** Clusters and kinds in their encoding order, which fixes colours and shapes. */
function legendOrder(visualization: Visualization) {
  const { node_color: cluster, node_shape: kind } = visualization.encoding
  return { clusters: (cluster?.order ?? []).map(String), kinds: (kind?.order ?? []).map(String) }
}

function clusterColor(clusters: string[], cluster: string | null | undefined): string {
  return cluster == null ? NO_CLUSTER : PALETTE[Math.max(clusters.indexOf(cluster), 0) % PALETTE.length]
}

export function NetworkGraph({ visualization, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const { clusters, kinds } = legendOrder(visualization)
  const { nodes } = visualization.data as NetworkData
  const lines = (visualization.encoding.edge_style?.order ?? []).map(String)
  const sponsorClasses = (visualization.encoding.node_category?.order ?? []).map(String)

  useEffect(() => {
    if (!container.current) return
    const { clusters, kinds } = legendOrder(visualization)
    const { nodes, edges } = visualization.data as NetworkData
    const range = (values: number[]) => [Math.min(...values, 1), Math.max(...values, 1)]
    const [nodeMin, nodeMax] = range(nodes.map((n) => n.trial_count))
    const [edgeMin, edgeMax] = range(edges.map((e) => e.trial_count))
    const strongest = Math.max(...edges.map((e) => e.association ?? 0), 0.01)
    const labels = new Map(nodes.map((n) => [n.id, n.label]))

    const cy = cytoscape({
      container: container.current,
      // Wheel zoom would capture page scrolling: scrolling over a full-width graph never reached
      // the legend and citations below it. Dragging still pans.
      userZoomingEnabled: false,
      elements: [
        ...nodes.map((n, i) => ({
          data: {
            id: n.id,
            label: n.label,
            weight: n.trial_count,
            color: n.anchor ? ANCHOR : clusterColor(clusters, n.community),
            shape: SHAPES[Math.max(kinds.indexOf(n.kind), 0) % SHAPES.length],
            border: n.sponsor_class ? (SPONSOR_CLASS[n.sponsor_class] ?? OTHER_CLASS).color : '#fff',
            index: i,
          },
          classes: [n.anchor ? 'anchor' : '', n.sponsor_class ? 'classed' : ''].join(' '),
        })),
        ...edges.map((e, i) => ({
          data: {
            id: `edge-${i}`,
            source: e.source,
            target: e.target,
            weight: e.trial_count,
            strength: e.association ?? 0,
            line: LINE[e.relation ?? '']?.style ?? 'solid',
            index: i,
          },
        })),
      ],
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': 'data(color)',
            shape: 'data(shape)' as never,
            width: `mapData(weight, ${nodeMin}, ${Math.max(nodeMax, nodeMin + 1)}, 14, 56)`,
            height: `mapData(weight, ${nodeMin}, ${Math.max(nodeMax, nodeMin + 1)}, 14, 56)`,
            'font-size': 9,
            'text-wrap': 'ellipsis',
            'text-max-width': '120px',
            'text-valign': 'bottom',
            'text-margin-y': 2,
            'text-background-color': '#fff',
            'text-background-opacity': 0.75,
            'text-background-padding': '1px',
          },
        },
        { selector: 'node.classed', style: { 'border-width': 3, 'border-color': 'data(border)' } },
        { selector: 'node.anchor', style: { 'border-width': 3, 'border-color': '#fff', 'font-weight': 'bold' } },
        {
          selector: 'edge',
          style: {
            width: `mapData(weight, ${edgeMin}, ${Math.max(edgeMax, edgeMin + 1)}, 1, 9)`,
            'line-color': '#5b6670',
            'line-style': 'data(line)' as never,
            opacity: (edge: cytoscape.EdgeSingular) => 0.12 + (0.73 * edge.data('strength')) / strongest,
          },
        },
        { selector: ':selected', style: { 'border-width': 3, 'border-color': '#111', 'line-color': '#111', opacity: 1 } },
      ],
      layout: {
        name: 'cose',
        animate: false,
        padding: 30,
        nodeRepulsion: () => 400_000,
        idealEdgeLength: () => 110,
        nodeOverlap: 40,
        gravity: 0.4,
        numIter: 2500,
      },
    })

    cy.on('tap', 'node', (event) => {
      const node = nodes[event.target.data('index')]
      const role = node.anchor ? 'anchor' : node.community ? `${node.community} cluster` : 'no cluster'
      onSelect({ label: `${node.label} · ${role} · ${node.partners ?? 0} partners`, count: node.trial_count, citations: node.citations })
    })
    cy.on('tap', 'edge', (event) => {
      const edge = edges[event.target.data('index')]
      const split =
        edge.combined_trials !== undefined
          ? ` · combined ${edge.combined_trials}, compared ${edge.compared_trials}`
          : edge.lead_trials !== undefined
            ? ` · leads ${edge.lead_trials}, collaborates ${edge.collaborator_trials}`
            : ''
      onSelect({
        label: `${labels.get(edge.source)} — ${labels.get(edge.target)} · association ${edge.association ?? '?'}${split}`,
        count: edge.trial_count,
        citations: edge.citations,
      })
    })
    return () => cy.destroy()
  }, [visualization, onSelect])

  return (
    <>
      <div ref={container} className="chart network" />
      <ul className="legend">
        {clusters.map((cluster) => (
          <li key={cluster}>
            <span className="swatch" style={{ background: clusterColor(clusters, cluster) }} />
            <span>{`${cluster} cluster`}</span>
          </li>
        ))}
        {nodes.some((n) => n.anchor) && (
          <li>
            <span className="swatch" style={{ background: ANCHOR }} />
            <span>anchor</span>
          </li>
        )}
        {nodes.some((n) => !n.anchor && n.community == null) && (
          <li>
            <span className="swatch" style={{ background: NO_CLUSTER }} />
            <span>no cluster</span>
          </li>
        )}
        {kinds.length > 1 &&
          kinds.map((kind, i) => (
            <li key={kind}>
              <span className={`swatch ${SHAPES[i % SHAPES.length]}`} />
              <span>{kind}</span>
            </li>
          ))}
        {lines.map((line) => (
          <li key={line}>
            <span className={`line-swatch ${LINE[line]?.style ?? 'solid'}`} />
            <span>{LINE[line]?.legend ?? line}</span>
          </li>
        ))}
        {sponsorClasses.map((c) => (
          <li key={c}>
            <span className="swatch classed" style={{ borderColor: (SPONSOR_CLASS[c] ?? OTHER_CLASS).color }} />
            <span>{(SPONSOR_CLASS[c] ?? OTHER_CLASS).legend}</span>
          </li>
        ))}
        <li className="muted">line width = shared trials · darker = stronger association</li>
      </ul>
    </>
  )
}
