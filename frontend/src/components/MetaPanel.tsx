import type { Meta } from '../api/types'

export function MetaPanel({ meta }: { meta: Meta }) {
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
                  {c.analyzed.toLocaleString()}
                  {c.truncated && <span className="badge">truncated</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ul className="notes">
        {meta.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
      <details>
        <summary>Plan (interpretation and filters)</summary>
        <pre>{JSON.stringify(meta.plan, null, 2)}</pre>
      </details>
      <p className="muted">Source: {meta.source}</p>
    </div>
  )
}
