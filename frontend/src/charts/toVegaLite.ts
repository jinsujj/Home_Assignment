import type { TopLevelSpec } from 'vega-lite'
import type { Channel, Row, Visualization } from '../api/types'

// Translates the service's chart spec into Vega-Lite using only `type` and `encoding`;
// nothing here knows which question produced the chart.

const title = (c: Channel) => (c.unit && c.type === 'quantitative' ? `${c.title} (${c.unit})` : c.title)

function axisChannel(c: Channel) {
  // time_unit "year" carries plain year numbers, so they plot as integers rather than timestamps.
  if (c.type === 'temporal' && c.time_unit === 'year') {
    return { field: c.field, type: 'quantitative' as const, title: title(c), axis: { format: 'd' }, scale: { zero: false } }
  }
  const categorical = c.type === 'nominal' || c.type === 'ordinal'
  return {
    field: c.field,
    type: c.type,
    title: title(c),
    ...(c.order ? { sort: c.order } : {}),
    ...(categorical ? { axis: { labelAngle: -30, labelLimit: 180 } } : {}),
  }
}

function seriesChannel(c: Channel) {
  return { field: c.field, type: c.type, title: c.title, ...(c.order ? { sort: c.order, scale: { domain: c.order } } : {}) }
}

export function toVegaLite(viz: Visualization): TopLevelSpec {
  const rows = viz.data as Row[]
  const { x, y, series, x2, tooltip } = viz.encoding
  const base = {
    $schema: 'https://vega.github.io/schema/vega-lite/v6.json' as const,
    width: 'container' as const,
    height: 380,
    autosize: { type: 'fit' as const, contains: 'padding' as const },
  }
  const tooltipFields = [x, ...(series ? [series] : []), y].map((c) => ({ field: c.field, title: c.title }))

  switch (viz.type) {
    case 'bar_chart':
      return { ...base, data: { values: rows }, mark: 'bar', encoding: { x: axisChannel(x), y: axisChannel(y), tooltip: tooltipFields } }

    case 'grouped_bar_chart':
      return {
        ...base,
        data: { values: rows },
        mark: 'bar',
        encoding: {
          x: axisChannel(x),
          y: axisChannel(y),
          xOffset: seriesChannel(series),
          color: seriesChannel(series),
          tooltip: tooltipFields,
        },
      }

    case 'time_series':
      return {
        ...base,
        data: { values: rows },
        mark: { type: 'line', point: true },
        encoding: {
          x: axisChannel(x),
          y: axisChannel(y),
          ...(series ? { color: seriesChannel(series) } : {}),
          tooltip: tooltipFields,
        },
      }

    case 'histogram': {
      // The last bin may be open-ended (bin_end null): draw it one bin wide and label it "≥ start".
      const width = rows.length > 0 && rows[0][x2.field] != null ? Number(rows[0][x2.field]) - Number(rows[0][x.field]) : 1
      const values = rows.map((r) => {
        const start = Number(r[x.field])
        const end = r[x2.field] == null ? null : Number(r[x2.field])
        return { ...r, _end: end ?? start + width, _range: end == null ? `≥ ${start}` : `${start} – ${end}` }
      })
      return {
        ...base,
        data: { values },
        mark: 'bar',
        encoding: {
          // Pre-binned data: without `binned`, Vega-Lite reads x/x2 as a horizontal range bar.
          x: { field: x.field, type: 'quantitative', title: title(x), bin: { binned: true, step: width } },
          x2: { field: '_end' },
          y: axisChannel(y),
          tooltip: [{ field: '_range', title: title(x) }, { field: y.field, title: y.title }],
        },
      }
    }

    case 'scatter_plot':
      return {
        ...base,
        data: { values: rows },
        mark: { type: 'point', filled: true, opacity: 0.55 },
        encoding: {
          x: axisChannel(x),
          y: axisChannel(y),
          tooltip: [
            ...(tooltip ? [{ field: tooltip.field, title: tooltip.title }] : []),
            { field: x.field, title: title(x) },
            { field: y.field, title: title(y) },
          ],
        },
      }

    case 'network_graph':
      throw new Error('network graphs are rendered with Cytoscape')
  }
}
