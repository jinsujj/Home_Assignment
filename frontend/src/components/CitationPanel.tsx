import type { Selection } from '../api/types'

export function CitationPanel({ selection }: { selection: Selection | null }) {
  if (!selection) {
    return <p className="hint">Click a bar, point, node or link to see the trials behind it.</p>
  }
  const { label, count, citations } = selection
  return (
    <div>
      <h3>
        {label} <span className="muted">· {count.toLocaleString()} trials</span>
      </h3>
      {citations.items.length < citations.total && (
        <p className="muted">
          Showing {citations.items.length} of {citations.total.toLocaleString()} cited trials
          {citations.total < count && ' (the analyzed ones; the count covers every matching trial)'}.
        </p>
      )}
      <ul className="citations">
        {citations.items.map((c) => (
          <li key={c.nct_id}>
            <a href={c.url} target="_blank" rel="noreferrer">
              {c.nct_id}
            </a>{' '}
            {c.title}
            <ul>
              {c.evidence.map((e) => (
                <li key={e.field + e.value}>
                  <code>{e.field.split('.').slice(-2).join('.')}</code> = <q>{e.value}</q>
                </li>
              ))}
              {c.mentioned_only.map((term) => (
                <li key={term} className="mentioned">
                  mentions <q>{term}</q> only in its text; not registered as such
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  )
}
