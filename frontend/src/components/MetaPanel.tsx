import type { Meta, Selection } from '../api/types'

interface Props {
  meta: Meta
  /** Shows the trials a note counts in the citation panel. */
  onSelect: (selection: Selection) => void
}

export function MetaPanel({ meta, onSelect }: Props) {
  const cited = new Map((meta.note_citations ?? []).map((n) => [n.note, n.citations]))
  return (
    <div className="meta">
      {meta.cohorts.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Cohort</th>
              <th>Matched</th>
              <th>Analyzed</th>
            </tr>
          </thead>
          <tbody>
            {meta.cohorts.map((c) => (
              <tr key={c.label}>
                <td>{c.label || '—'}</td>
                <td>{c.matched.toLocaleString()}</td>
                <td>
                  <span>{c.analyzed.toLocaleString()}</span>
                  {c.truncated && <span className="badge">truncated</span>}
                  {c.exact_counts && <span className="badge">exact counts</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ul className="notes">
        {meta.notes.map((note) => {
          const citations = cited.get(note)
          return (
            <li key={note}>
              <span>{note}</span>
              {citations && (
                <>
                  {' '}
                  <button
                    type="button"
                    className="link small"
                    onClick={() => onSelect({ label: note, count: citations.total, citations })}
                  >
                    show trials
                  </button>
                </>
              )}
            </li>
          )
        })}
      </ul>
      <details>
        <summary>Plan (interpretation and filters)</summary>
        <pre>{JSON.stringify(meta.plan, null, 2)}</pre>
      </details>
      <p className="muted">
        {`Source: ${meta.source}` + (meta.data_version ? ` · data snapshot ${meta.data_version}` : '')}
      </p>
    </div>
  )
}
