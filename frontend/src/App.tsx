import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, askQuestion, getOptions, getVersion, runPlan } from './api/client'
import { resolvedViews } from './api/references'
import type { NetworkData, SearchOptions, Selection, View, Visualization, VisualizationResponse } from './api/types'
import { CitationPanel } from './components/CitationPanel'
import { Composer } from './components/Composer'
import { MetaPanel } from './components/MetaPanel'
import { NetworkGraph } from './components/NetworkGraph'
import { VegaChart } from './components/VegaChart'
import { type Entry, entryKey, loadHistory, remember, saveHistory } from './history'
import { EXAMPLES, type StructuredFields } from './presets'

type Call = (request: unknown, signal: AbortSignal) => Promise<VisualizationResponse>
type Asked = Pick<Entry, 'key' | 'query' | 'fields'>

const questionRequest = (query: string, fields: StructuredFields) => ({ query, ...fields })
const askedOf = (entry: Entry): Asked => ({ key: entry.key, query: entry.query, fields: entry.fields })
/** "2026-10-09T09:00:05" -> "2026-10-09 09:00" */
const snapshot = (version: string) => version.replace('T', ' ').slice(0, 16)

const describeFields = (fields: StructuredFields) =>
  Object.entries(fields)
    .map(([name, value]) => `${name.replace('_name', '')}: ${Array.isArray(value) ? value.join(', ') : value}`)
    .join(' · ')

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

/** Tab name for a view; an alternative drawn as a bar chart or time series is named by what it shows. */
function viewLabel(view: Visualization, index: number, answer: Visualization): string {
  if (index > 0 && view.type === 'time_series') return 'Cumulative'
  if (index > 0 && view.type === 'bar_chart') return answer.type === 'scatter_plot' ? 'Medians' : 'Top links'
  return VIEW_LABELS[view.type] ?? view.type
}

const isEmpty = (viz: Visualization) =>
  Array.isArray(viz.data) ? viz.data.length === 0 : (viz.data as NetworkData).nodes.length === 0

export default function App() {
  // A reload shows the last answer of this session instead of asking again.
  const [history, setHistory] = useState<Entry[]>(loadHistory)
  const last: Entry | undefined = history[0]
  const [activeKey, setActiveKey] = useState<string | null>(last?.key ?? null)
  const [query, setQuery] = useState(last?.query ?? EXAMPLES[0].query)
  const [fields, setFields] = useState<StructuredFields>(last?.fields ?? EXAMPLES[0].fields ?? {})
  const [planText, setPlanText] = useState(last?.response ? JSON.stringify({ plan: last.response.meta.plan }, null, 2) : '')
  const [result, setResult] = useState<VisualizationResponse | null>(last?.response ?? null)
  const [error, setError] = useState<{ message: string; explained: boolean } | null>(
    last?.notice ? { message: last.notice, explained: true } : null,
  )
  const [loading, setLoading] = useState(!last)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [showRaw, setShowRaw] = useState(false)
  const [viewIndex, setViewIndex] = useState(0)
  const [options, setOptions] = useState<SearchOptions | null>(null)
  const inFlight = useRef<AbortController | null>(null)
  const restored = useRef(history.length > 0)
  const knownVersion = useRef<string | null>(last?.dataVersion ?? null)
  // Bumped by every start or show, so a late version check cannot replace what the user chose since.
  const generation = useRef(0)

  useEffect(() => saveHistory(history), [history])

  // Choices for the filter fields; without them the fields still accept free text.
  useEffect(() => {
    const controller = new AbortController()
    getOptions(controller.signal)
      .then(setOptions)
      .catch(() => setOptions(null))
    return () => controller.abort()
  }, [])

  // State changes only once the response arrives; a newer request aborts the older one.
  const send = useCallback((call: Call, request: unknown, asked?: Asked) => {
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    call(request, controller.signal)
      .then((response) => {
        setResult(response)
        setViewIndex(0)
        setPlanText(JSON.stringify({ plan: response.meta.plan }, null, 2))
        setError(null)
        knownVersion.current = response.meta.data_version ?? knownVersion.current
        if (asked) setHistory((h) => remember(h, { ...asked, response, dataVersion: response.meta.data_version }))
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) {
          // The previous chart answered another question; keeping it under this message misleads.
          const message = e instanceof Error ? e.message : String(e)
          const explained = e instanceof ApiError && !!e.code
          setResult(null)
          setError({ message, explained })
          // Explained answers (refusals, unknown trials) are answers too; failures are retried.
          if (asked && explained) {
            setHistory((h) => remember(h, { ...asked, notice: message, dataVersion: knownVersion.current }))
          }
        }
      })
      .finally(() => {
        if (inFlight.current === controller) setLoading(false)
      })
  }, [])

  // Answer the first example on a first visit; the initial state already says "loading".
  // A restored answer is asked again if the registry has published newer data since.
  useEffect(() => {
    if (!restored.current) {
      const { query, fields = {} } = EXAMPLES[0]
      send(askQuestion, questionRequest(query, fields), { key: entryKey(query, fields), query, fields })
      return () => inFlight.current?.abort()
    }
    const controller = new AbortController()
    const [last] = loadHistory()
    getVersion(controller.signal)
      .then((current) => {
        if (last && current && current !== last.dataVersion && generation.current === 0) {
          setLoading(true)
          send(askQuestion, questionRequest(last.query, last.fields), askedOf(last))
        }
      })
      .catch(() => {})
    return () => controller.abort()
  }, [send])

  const start = (call: Call, request: unknown, asked?: Asked) => {
    generation.current++
    setLoading(true)
    setError(null)
    setSelection(null)
    setActiveKey(asked?.key ?? null)
    send(call, request, asked)
  }

  /** Shows a stored answer: no planning, no query. */
  const show = (entry: Entry) => {
    generation.current++
    inFlight.current?.abort()
    setLoading(false)
    setActiveKey(entry.key)
    setQuery(entry.query)
    setFields(entry.fields)
    setResult(entry.response ?? null)
    setError(entry.notice ? { message: entry.notice, explained: true } : null)
    setViewIndex(0)
    setSelection(null)
    if (entry.response) setPlanText(JSON.stringify({ plan: entry.response.meta.plan }, null, 2))
  }

  /** A stored answer, or a fresh one when the service now serves newer registry data. */
  const open = (entry: Entry) => {
    const current = ++generation.current
    getVersion()
      .catch(() => null) // the service is unreachable: the stored answer is the best there is
      .then((version) => {
        if (generation.current !== current) return
        if (version && version !== entry.dataVersion) {
          setQuery(entry.query)
          setFields(entry.fields)
          start(askQuestion, questionRequest(entry.query, entry.fields), askedOf(entry))
        } else {
          show(entry)
        }
      })
  }

  const showTrial = (nctId: string) => {
    const next = { ...fields, nct_id: nctId }
    setFields(next)
    ask(query, next)
  }

  const ask = (text = query, structured = fields) => {
    const question = text.trim()
    if (!question) return
    const key = entryKey(question, structured)
    const known = history.find((entry) => entry.key === key)
    if (known) open(known)
    else start(askQuestion, questionRequest(question, structured), { key, query: question, fields: structured })
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

  const alternatives = useMemo(() => (result ? resolvedViews(result) : []), [result])
  const views: (Visualization | View)[] = result ? [result.visualization, ...alternatives] : []
  const viz = views[viewIndex] ?? result?.visualization

  return (
    <div className="app">
      <aside>
        <h1>Cheiron</h1>
        <p className="muted">Questions about ClinicalTrials.gov, answered with charts</p>

        {history.length > 0 && (
          <>
            <h2>
              Recent{' '}
              <button type="button" className="link small" onClick={() => setHistory([])}>
                clear
              </button>
            </h2>
            <ol className="presets recent">
              {history.map((entry) => (
                <li key={entry.key}>
                  <button className={entry.key === activeKey ? 'active' : ''} onClick={() => open(entry)}>
                    {entry.query}
                    {Object.keys(entry.fields).length > 0 && <span className="muted"> ({describeFields(entry.fields)})</span>}
                    {entry.notice && <span className="muted"> · no chart</span>}
                  </button>
                </li>
              ))}
            </ol>
          </>
        )}

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
          {!result && loading && (
            <p className="muted">
              <span className="spinner" aria-hidden="true" />
              Planning and querying ClinicalTrials.gov…
            </p>
          )}
          {result && viz && (
            <>
              <header className={loading ? 'stale' : ''}>
                <span className="type">{viz.type}</span>
                {result.meta.data_version && (
                  <span className="muted"> ClinicalTrials.gov data of {snapshot(result.meta.data_version)}</span>
                )}
                {loading && (
                  <span className="muted">
                    {' '}
                    <span className="spinner" aria-hidden="true" />
                    Working…
                  </span>
                )}
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
                        {viewLabel(view, index, result.visualization)}
                      </button>
                    ))}
                  </div>
                )}
                {isEmpty(viz) ? (
                  <p className="notice">Nothing to chart for this question; the notes under Meta say why.</p>
                ) : viz.type === 'network_graph' ? (
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
                  <CitationPanel
                    key={selection ? `${selection.label}|${selection.count}` : 'none'}
                    selection={selection}
                    names={
                      result.meta.cohorts.find((c) => c.label === (selection?.cohort ?? result.meta.cohorts[0]?.label))
                        ?.names ?? []
                    }
                  />
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
