import cytoscape from 'cytoscape'
import { useEffect, useRef } from 'react'
import type { NetworkData, Selection, Visualization } from '../api/types'

const PALETTE = ['#2f6fdd', '#e0782f', '#2a9d6f', '#9b5de5']

interface Props {
  visualization: Visualization
  onSelect: (selection: Selection) => void
}

export function NetworkGraph({ visualization, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!container.current) return
    const { nodes, edges } = visualization.data as NetworkData
    const kinds = (visualization.encoding.node_color.order ?? []).map(String)
    const color = (kind: string) => PALETTE[Math.max(kinds.indexOf(kind), 0) % PALETTE.length]
    const range = (values: number[]) => [Math.min(...values, 1), Math.max(...values, 1)]
    const [nodeMin, nodeMax] = range(nodes.map((n) => n.trial_count))
    const [edgeMin, edgeMax] = range(edges.map((e) => e.trial_count))
    const labels = new Map(nodes.map((n) => [n.id, n.label]))

    const cy = cytoscape({
      container: container.current,
      elements: [
        ...nodes.map((n, i) => ({ data: { id: n.id, label: n.label, weight: n.trial_count, color: color(n.kind), index: i } })),
        ...edges.map((e, i) => ({ data: { id: `edge-${i}`, source: e.source, target: e.target, weight: e.trial_count, index: i } })),
      ],
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': 'data(color)',
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
        {
          selector: 'edge',
          style: {
            width: `mapData(weight, ${edgeMin}, ${Math.max(edgeMax, edgeMin + 1)}, 1, 9)`,
            'line-color': '#9aa3ad',
            opacity: 0.6,
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
      onSelect({ label: node.label, count: node.trial_count, citations: node.citations })
    })
    cy.on('tap', 'edge', (event) => {
      const edge = edges[event.target.data('index')]
      onSelect({
        label: `${labels.get(edge.source)} — ${labels.get(edge.target)}`,
        count: edge.trial_count,
        citations: edge.citations,
      })
    })
    return () => cy.destroy()
  }, [visualization, onSelect])

  return <div ref={container} className="chart network" />
}
