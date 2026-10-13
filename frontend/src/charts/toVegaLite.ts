import type { TopLevelSpec } from 'vega-lite'
import world from 'world-atlas/countries-110m.json'
import type { Channel, Row, Visualization } from '../api/types'

// Translates the service's chart spec into Vega-Lite using only `type` and `encoding`;
// nothing here knows which question produced the chart.

const title = (c: Channel) => (c.unit && (c.type === 'quantitative' || c.type === 'ordinal') ? `${c.title} (${c.unit})` : c.title)

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

/** Vega's symlog ticks are spaced linearly, so a log-like axis gets 0 and powers of ten. */
function scaledChannel(c: Channel, rows: Row[]) {
  if (c.scale !== 'symlog') return axisChannel(c)
  const max = Math.max(...rows.map((r) => Number(r[c.field]) || 0))
  const ticks = [0]
  for (let tick = 10; tick <= max; tick *= 10) ticks.push(tick)
  return { ...axisChannel(c), scale: { type: 'symlog' as const }, axis: { values: ticks } }
}

function seriesChannel(c: Channel) {
  return { field: c.field, type: c.type, title: c.title, ...(c.order ? { sort: c.order, scale: { domain: c.order } } : {}) }
}

function rowChannel(c: Channel) {
  return { field: c.field, type: 'nominal' as const, title: c.title, axis: { labelLimit: 260 }, ...(c.order ? { sort: c.order } : {}) }
}

const tips = (...channels: (Channel | undefined)[]) =>
  channels.filter((c): c is Channel => !!c).map((c) => ({ field: c.field, title: title(c) }))

export function toVegaLite(viz: Visualization): TopLevelSpec {
  const rows = viz.data as Row[]
  const { x, y, series, x2, tooltip, color, y_lower: lower, y_upper: upper } = viz.encoding
  const base = {
    $schema: 'https://vega.github.io/schema/vega-lite/v6.json' as const,
    width: 'container' as const,
    height: 380,
    autosize: { type: 'fit' as const, contains: 'padding' as const },
  }
  const tooltipFields = () => tips(x, series, y, tooltip)

  switch (viz.type) {
    case 'bar_chart':
      return { ...base, data: { values: rows }, mark: 'bar', encoding: { x: axisChannel(x), y: axisChannel(y), tooltip: tooltipFields() } }

    case 'grouped_bar_chart': {
      const grouped = { x: axisChannel(x), xOffset: seriesChannel(series), color: seriesChannel(series) }
      if (!lower || !upper) {
        return { ...base, data: { values: rows }, mark: 'bar', encoding: { ...grouped, y: axisChannel(y), tooltip: tooltipFields() } }
      }
      // Posted intervals (e.g. 95% CI) drawn as error bars over the bars.
      const interval = [
        { field: lower.field, title: lower.title },
        { field: upper.field, title: upper.title },
      ]
      return {
        ...base,
        data: { values: rows },
        encoding: grouped,
        layer: [
          { mark: 'bar', encoding: { y: axisChannel(y), tooltip: [...tooltipFields(), ...interval] } },
          {
            mark: { type: 'rule', strokeWidth: 1.5 },
            encoding: { y: { field: lower.field, type: 'quantitative' }, y2: { field: upper.field }, color: { value: '#1d2228' } },
          },
        ],
      }
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
          tooltip: tooltipFields(),
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
          x: scaledChannel(x, rows),
          y: scaledChannel(y, rows),
          tooltip: [
            ...(tooltip ? [{ field: tooltip.field, title: tooltip.title }] : []),
            { field: x.field, title: title(x) },
            { field: y.field, title: title(y) },
          ],
        },
      }

    case 'stacked_bar_chart':
      return {
        ...base,
        data: { values: rows },
        mark: 'bar',
        encoding: {
          x: axisChannel(x),
          y: { field: y.field, type: 'quantitative', title: title(y), stack: 'zero', scale: { domain: [0, 100] } },
          color: seriesChannel(color),
          tooltip: tips(x, color, y),
        },
      }

    case 'heatmap':
      return {
        ...base,
        data: { values: rows },
        mark: 'rect',
        encoding: {
          x: axisChannel(x),
          y: rowChannel(y),
          color: { field: color.field, type: 'quantitative', title: title(color), scale: { scheme: 'blues' } },
          tooltip: tips(x, y, color),
        },
      }

    case 'donut_chart': {
      const { theta } = viz.encoding
      return {
        ...base,
        data: { values: rows },
        mark: { type: 'arc', innerRadius: 80 },
        encoding: {
          theta: { field: theta.field, type: 'quantitative', stack: true },
          color: seriesChannel(color),
          tooltip: tips(color, theta, tooltip),
        },
      }
    }

    case 'choropleth_map': {
      // Registry rows joined to world shapes by ISO 3166-1 numeric code (the shapes' `id`).
      const { region, label } = viz.encoding
      // Two layers: every country in grey, then the ones with data in colour (Vega-Lite drops
      // shapes whose colour value is null, so one layer would erase countries without data).
      const shapes = { values: world, format: { type: 'topojson' as const, feature: 'countries' } }
      return {
        ...base,
        height: 420,
        projection: { type: 'equalEarth' },
        layer: [
          { data: shapes, mark: { type: 'geoshape', fill: '#e8ebef', stroke: '#fff', strokeWidth: 0.5 } },
          {
            data: shapes,
            transform: [
              { lookup: 'id', from: { data: { values: rows }, key: region.field, fields: [label.field, color.field, 'citations'] } },
              { filter: `datum['${color.field}'] != null` },
            ],
            mark: { type: 'geoshape', stroke: '#fff', strokeWidth: 0.5 },
            encoding: {
              color: { field: color.field, type: 'quantitative', title: title(color), scale: { scheme: 'blues' } },
              tooltip: [{ field: 'properties.name', title: 'Country' }, ...tips(color)],
            },
          },
        ],
      }
    }

    case 'line_chart':
      return {
        ...base,
        data: { values: rows },
        mark: { type: 'line', point: true },
        encoding: { x: axisChannel(x), y: axisChannel(y), tooltip: tips(x, y) },
      }

    case 'forest_plot': {
      const { x_lower: from, x_upper: to } = viz.encoding
      return {
        ...base,
        data: { values: rows },
        encoding: { y: rowChannel(y), yOffset: seriesChannel(series), color: seriesChannel(series) },
        layer: [
          {
            mark: { type: 'rule', strokeWidth: 2 },
            encoding: { x: { field: from.field, type: 'quantitative', title: title(x) }, x2: { field: to.field } },
          },
          {
            mark: { type: 'point', filled: true, size: 90, opacity: 1 },
            encoding: { x: { field: x.field, type: 'quantitative', title: title(x) }, tooltip: tips(y, series, x, from, to) },
          },
        ],
      }
    }

    case 'network_graph':
      throw new Error('network graphs are rendered with Cytoscape')
  }
}
