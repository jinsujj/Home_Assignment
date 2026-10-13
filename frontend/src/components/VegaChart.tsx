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
          // trial_count may cover more trials than are cited (registry counts beyond the cap)
          count: Number(datum.trial_count ?? datum.citations.total),
          citations: datum.citations,
          cohort: typeof datum.cohort === 'string' ? datum.cohort : undefined,
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
