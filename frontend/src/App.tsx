import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, askQuestion, getOptions, runPlan } from './api/client'
import type { SearchOptions, Selection, View, Visualization, VisualizationResponse } from './api/types'
import { CitationPanel } from './components/CitationPanel'
import { Composer } from './components/Composer'
import { MetaPanel } from './components/MetaPanel'
import { NetworkGraph } from './components/NetworkGraph'
import { VegaChart } from './components/VegaChart'
import { EXAMPLES, type StructuredFields } from './presets'

type Call = (request: unknown, signal: AbortSignal) => Promise<VisualizationResponse>

const questionRequest = (query: string, fields: StructuredFields) => ({ query, ...fields })

const VIEW_LABELS: Record<string, string> = {
  bar_chart: 'Bars',
  grouped_bar_chart: 'Grouped bars',
  time_series: 'Over time',
  histogram: 'Histogram',
  scatter_plot: 'Scatter',
  network_graph: 'Network',
  stacked_bar_chart: 'Mix (100%)',
  heatmap: 'Heatmap',
  choropleth_map: 'Map',
  donut_chart: 'Donut',
  line_chart: 'Cumulative',
  forest_plot: 'Intervals',
}

/** Tab name for a view; alternatives sharing a type with the answer are named by their title. */
function viewLabel(view: Visualization, index: number): string {
  if (index > 0 && view.type === 'time_series') return 'Cumulative'
  if (index > 0 && view.type === 'bar_chart') return 'Top links'
  return VIEW_LABELS[view.type] ?? view.type
}

export default function App() {
  const [query, setQuery] = useState(EXAMPLES[0].query)
  const [fields, setFields] = useState<StructuredFields>(EXAMPLES[0].fields ?? {})
  const [planText, setPlanText] = useState('')
  const [result, setResult] = useState<VisualizationResponse | null>(null)
  const [error, setError] = useState<{ message: string; explained: boolean } | null>(null)
  const [loading, setLoading] = useState(true)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [showRaw, setShowRaw] = useState(false)
  const [viewIndex, setViewIndex] = useState(0)
  const [options, setOptions] = useState<SearchOptions | null>(null)
  const inFlight = useRef<AbortController | null>(null)

  // Choices for the filter fields; without them the fields still accept free text.
  useEffect(() => {
    const controller = new AbortController()
    getOptions(controller.signal)
      .then(setOptions)
      .catch(() => setOptions(null))
    return () => controller.abort()
  }, [])

  // State changes only once the response arrives; a newer request aborts the older one.
  const send = useCallback((call: Call, request: unknown) => {
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    call(request, controller.signal)
      .then((response) => {
        setResult(response)
        setViewIndex(0)
        setPlanText(JSON.stringify({ plan: response.meta.plan }, null, 2))
        setError(null)
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) {
          // The previous chart answered another question; keeping it under this message misleads.
          setResult(null)
          setError({ message: e instanceof Error ? e.message : String(e), explained: e instanceof ApiError && !!e.code })
        }
      })
      .finally(() => {
        if (inFlight.current === controller) setLoading(false)
      })
  }, [])

  // Answer the first example on load; the initial state already says "loading".
  useEffect(() => {
    send(askQuestion, questionRequest(EXAMPLES[0].query, EXAMPLES[0].fields ?? {}))
    return () => inFlight.current?.abort()
  }, [send])

  const start = (call: Call, request: unknown) => {
    setLoading(true)
    setError(null)
    setSelection(null)
    send(call, request)
  }

  const showTrial = (nctId: string) => {
    const next = { ...fields, nct_id: nctId }
    setFields(next)
    ask(query, next)
  }

  const ask = (text = query, structured = fields) => {
    if (text.trim()) start(askQuestion, questionRequest(text.trim(), structured))
  }

  const choose = (index: number) => {
    const example = EXAMPLES[index]
    setQuery(example.query)
    setFields(example.fields ?? {})
    ask(example.query, example.fields ?? {})
  }

  const runEditedPlan = () => {
    try {
      start(runPlan, JSON.parse(planText))
    } catch (e) {
      setError({ message: `Invalid JSON: ${(e as Error).message}`, explained: false })
    }
  }

  const views: (Visualization | View)[] = result ? [result.visualization, ...result.alternatives] : []
  const viz = views[viewIndex] ?? result?.visualization

  return (
    <div className="app">
      <aside>
        <h1>Cheiron</h1>
        <p className="muted">Questions about ClinicalTrials.gov, answered with charts</p>

        <h2>Example questions</h2>
        <ol className="presets">
          {EXAMPLES.map((example, index) => (
            <li key={example.query}>
              <button onClick={() => choose(index)}>
                {example.query}
                {example.fields?.drug_name && <span className="muted"> (drug: {example.fields.drug_name})</span>}
              </button>
            </li>
          ))}
        </ol>

        <details className="plan-editor">
          <summary>
            Edit and rerun the plan <code>POST /api/plans</code>
          </summary>
          <textarea value={planText} onChange={(e) => setPlanText(e.target.value)} spellCheck={false} />
          <button className="secondary" onClick={runEditedPlan} disabled={loading || !planText}>
            Run plan
          </button>
        </details>
      </aside>

      <main>
        <div className="results">
          {error && <pre className={error.explained ? 'notice' : 'error'}>{error.message}</pre>}
          {!result && loading && <p className="muted">Planning and querying ClinicalTrials.gov…</p>}
          {result && viz && (
            <>
              <header className={loading ? 'stale' : ''}>
                <span className="type">{viz.type}</span>
                {loading && <span className="muted"> Working…</span>}
                <h2>{viz.title}</h2>
                {result.meta.interpretation && (
                  <p className="interpretation">
                    <strong>Understood as:</strong> {result.meta.interpretation}
                  </p>
                )}
                {result.meta.trial && (
                  <div className="trial">
                    <strong>Trial:</strong>{' '}
                    <a href={result.meta.trial.url} target="_blank" rel="noreferrer">
                      {result.meta.trial.nct_id}
                    </a>{' '}
                    {result.meta.trial.title}
                    {result.meta.trial.alternatives.length > 0 && (
                      <ul>
                        {result.meta.trial.alternatives.map((t) => (
                          <li key={t.nct_id}>
                            Also matched{' '}
                            <a href={t.url} target="_blank" rel="noreferrer">
                              {t.nct_id}
                            </a>{' '}
                            {t.title} ({t.enrollment ?? '?'} participants){' '}
                            <button type="button" className="link" onClick={() => showTrial(t.nct_id)}>
                              Show this trial
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </header>
              <section className={`card ${loading ? 'stale' : ''}`}>
                {views.length > 1 && (
                  <div className="views" role="tablist" aria-label="Chart views">
                    {views.map((view, index) => (
                      <button
                        key={`${view.type}-${index}`}
                        type="button"
                        role="tab"
                        aria-selected={index === viewIndex}
                        className={index === viewIndex ? 'view on' : 'view'}
                        onClick={() => {
                          setViewIndex(index)
                          setSelection(null)
                        }}
                      >
                        {viewLabel(view, index)}
                      </button>
                    ))}
                  </div>
                )}
                {viz.type === 'network_graph' ? (
                  <NetworkGraph visualization={viz} onSelect={setSelection} />
                ) : (
                  <VegaChart visualization={viz} onSelect={setSelection} />
                )}
                {'notes' in viz && viz.notes.length > 0 && (
                  <ul className="view-notes">
                    {viz.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                )}
              </section>
              <div className="columns">
                <section className="card">
                  <h3>Citations</h3>
                  <CitationPanel selection={selection} />
                </section>
                <section className="card">
                  <h3>Meta</h3>
                  <MetaPanel meta={result.meta} />
                </section>
              </div>
              <details className="card" onToggle={(e) => setShowRaw(e.currentTarget.open)}>
                <summary>Raw response</summary>
                {showRaw && <pre>{JSON.stringify(result, null, 2)}</pre>}
              </details>
            </>
          )}
        </div>
        <Composer
          query={query}
          onQueryChange={setQuery}
          fields={fields}
          onFieldsChange={setFields}
          options={options}
          loading={loading}
          onAsk={() => ask()}
        />
      </main>
    </div>
  )
}
