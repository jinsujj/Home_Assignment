import { useEffect, useRef } from 'react'
import embed from 'vega-embed'
import type { Row, Selection, Visualization } from '../api/types'
import { toVegaLite } from '../charts/toVegaLite'

interface Props {
  visualization: Visualization
  onSelect: (selection: Selection) => void
}

export function VegaChart({ visualization, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!container.current) return
    // Name a clicked datum by its categorical channels, whatever the chart type.
    const named = Object.values(visualization.encoding).filter((c) => c.type !== 'quantitative').map((c) => c.field)
    let finalize = () => {}
    let cancelled = false

    embed(container.current, toVegaLite(visualization), { actions: false, renderer: 'svg' }).then((result) => {
      if (cancelled) return result.finalize()
      finalize = () => result.finalize()
      result.view.addEventListener('click', (_event, item) => {
        const datum = (item as { datum?: Row } | null)?.datum
        if (!datum?.citations) return
        const parts = [...new Set(named)].map((field) => datum[field]).concat(datum._range)
        onSelect({
          label: parts.filter((p) => p != null && p !== '').join(' · ') || String(datum.title ?? ''),
          count: datum.citations.total,
          citations: datum.citations,
        })
      })
    })
    return () => {
      cancelled = true
      finalize()
    }
  }, [visualization, onSelect])

  return <div ref={container} className="chart" />
}
