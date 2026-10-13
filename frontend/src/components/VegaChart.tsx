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
    const { x, y, series } = visualization.encoding
    let finalize = () => {}
    let cancelled = false

    embed(container.current, toVegaLite(visualization), { actions: false, renderer: 'svg' }).then((result) => {
      if (cancelled) return result.finalize()
      finalize = () => result.finalize()
      result.view.addEventListener('click', (_event, item) => {
        const datum = (item as { datum?: Row } | null)?.datum
        if (!datum?.citations) return
        const parts = [datum[x.field], series ? datum[series.field] : null, datum._range]
        onSelect({
          label: parts.filter((p) => p != null && p !== '').join(' · ') || String(datum.title ?? ''),
          count: Number(datum[y.field] ?? datum.citations.total),
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
