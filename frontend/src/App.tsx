import { useCallback, useEffect, useRef, useState } from 'react'
import { runPlan } from './api/client'
import type { Selection, VisualizationResponse } from './api/types'
import { CitationPanel } from './components/CitationPanel'
import { MetaPanel } from './components/MetaPanel'
import { NetworkGraph } from './components/NetworkGraph'
import { VegaChart } from './components/VegaChart'
import { PRESETS } from './presets'

const asText = (request: unknown) => JSON.stringify(request, null, 2)

export default function App() {
  const [active, setActive] = useState(0)
  const [requestText, setRequestText] = useState(() => asText(PRESETS[0].request))
  const [result, setResult] = useState<VisualizationResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [showRaw, setShowRaw] = useState(false)
  const inFlight = useRef<AbortController | null>(null)

  // State changes only once the response arrives; a newer request aborts the older one.
  const fetchResult = useCallback((request: unknown) => {
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    runPlan(request, controller.signal)
      .then((response) => {
        setResult(response)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (inFlight.current === controller) setLoading(false)
      })
  }, [])

  // Show the first example on load; the initial state already says "loading".
  useEffect(() => {
    fetchResult(PRESETS[0].request)
    return () => inFlight.current?.abort()
  }, [fetchResult])

  const run = (text: string) => {
    let request: unknown
    try {
      request = JSON.parse(text)
    } catch (e) {
      setError(`Invalid JSON: ${(e as Error).message}`)
      return
    }
    setLoading(true)
    setError(null)
    setSelection(null)
    fetchResult(request)
  }

  const choose = (index: number) => {
    const text = asText(PRESETS[index].request)
    setActive(index)
    setRequestText(text)
    run(text)
  }

  const viz = result?.visualization

  return (
    <div className="app">
      <aside>
        <h1>Cheiron</h1>
        <p className="muted">ClinicalTrials.gov questions → visualization specs</p>

        <h2>Example questions</h2>
        <ol className="presets">
          {PRESETS.map((preset, index) => (
            <li key={preset.question}>
              <button className={index === active ? 'active' : ''} onClick={() => choose(index)}>
                {preset.question}
              </button>
            </li>
          ))}
        </ol>

        <h2>
          Plan request <code>POST /api/plans</code>
        </h2>
        <textarea value={requestText} onChange={(e) => setRequestText(e.target.value)} spellCheck={false} />
        <button className="primary" onClick={() => run(requestText)} disabled={loading}>
          {loading ? 'Running…' : 'Run plan'}
        </button>
      </aside>

      <main>
        {error && <pre className="error">{error}</pre>}
        {!result && loading && <p className="muted">Querying ClinicalTrials.gov…</p>}
        {result && viz && (
          <>
            <header className={loading ? 'stale' : ''}>
              <span className="type">{viz.type}</span>
              {loading && <span className="muted"> Querying ClinicalTrials.gov…</span>}
              <h2>{viz.title}</h2>
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
