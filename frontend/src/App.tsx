import { useCallback, useEffect, useRef, useState } from 'react'
import { askQuestion, getOptions, runPlan } from './api/client'
import type { SearchOptions, Selection, VisualizationResponse } from './api/types'
import { CitationPanel } from './components/CitationPanel'
import { FilterFields } from './components/FilterFields'
import { MetaPanel } from './components/MetaPanel'
import { NetworkGraph } from './components/NetworkGraph'
import { VegaChart } from './components/VegaChart'
import { EXAMPLES, type StructuredFields } from './presets'

type Call = (request: unknown, signal: AbortSignal) => Promise<VisualizationResponse>

const questionRequest = (query: string, fields: StructuredFields) => ({ query, ...fields })

export default function App() {
  const [query, setQuery] = useState(EXAMPLES[0].query)
  const [fields, setFields] = useState<StructuredFields>(EXAMPLES[0].fields ?? {})
  const [planText, setPlanText] = useState('')
  const [result, setResult] = useState<VisualizationResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [showRaw, setShowRaw] = useState(false)
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
        setPlanText(JSON.stringify({ plan: response.meta.plan }, null, 2))
        setError(null)
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
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
      setError(`Invalid JSON: ${(e as Error).message}`)
    }
  }

  const viz = result?.visualization

  return (
    <div className="app">
      <aside>
        <h1>Cheiron</h1>
        <p className="muted">Questions about ClinicalTrials.gov, answered with charts</p>

        <form
          className="ask"
          onSubmit={(e) => {
            e.preventDefault()
            ask()
          }}
        >
          <textarea
            className="question"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                ask()
              }
            }}
            placeholder="Ask about clinical trials…"
          />
          <details className="fields" open={Object.keys(fields).length > 0}>
            <summary>
              Filters (optional){Object.keys(fields).length > 0 && ` · ${Object.keys(fields).length} set`}
            </summary>
            <FilterFields value={fields} onChange={setFields} options={options} />
          </details>
          <button className="primary" type="submit" disabled={loading}>
            {loading ? 'Working…' : 'Ask'}
          </button>
        </form>

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
        {error && <pre className="error">{error}</pre>}
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
            </header>
            <section className={`card ${loading ? 'stale' : ''}`}>
              {viz.type === 'network_graph' ? (
                <NetworkGraph visualization={viz} onSelect={setSelection} />
              ) : (
                <VegaChart visualization={viz} onSelect={setSelection} />
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
      </main>
    </div>
  )
}
