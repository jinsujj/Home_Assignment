import { useState } from 'react'
import { judgeMentions } from '../api/client'
import type { MentionRole, MentionVerdict, Selection } from '../api/types'

const ROLES: Record<MentionRole, string> = {
  studied: 'studied by the trial',
  given_alongside: 'given alongside what the trial tests',
  eligibility: 'an eligibility condition',
  background: 'background only',
  unclear: 'unclear',
}

interface Props {
  selection: Selection | null
  /** What the cohort's filtered entity is called; empty when the cohort has no text filter. */
  names: string[]
}

export function CitationPanel({ selection, names }: Props) {
  const [verdicts, setVerdicts] = useState<Record<string, MentionVerdict> | null>(null)
  const [judging, setJudging] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  if (!selection) {
    return <p className="hint">Click a bar, point, node or link to see the trials behind it.</p>
  }
  const { label, count, citations } = selection

  const judge = () => {
    setJudging(true)
    setProblem(null)
    judgeMentions(
      citations.items.map((c) => c.nct_id),
      names,
    )
      .then((found) => setVerdicts(Object.fromEntries(found.map((v) => [v.nct_id, v]))))
      .catch((e: unknown) => setProblem(e instanceof Error ? e.message : String(e)))
      .finally(() => setJudging(false))
  }

  return (
    <div>
      <h3>
        <span>{label}</span> <span className="muted">{`· ${count.toLocaleString()} trials`}</span>
      </h3>
      {citations.items.length < citations.total && (
        <p className="muted">
          {`Showing ${citations.items.length} of ${citations.total.toLocaleString()} cited trials` +
            (citations.total < count ? ' (the analyzed ones; the count covers every matching trial).' : '.')}
        </p>
      )}
      {citations.registry_query && (
        <p className="muted">
          ClinicalTrials.gov counted these {count.toLocaleString()} trials:{' '}
          <a href={citations.registry_query} target="_blank" rel="noreferrer">
            reproduce the count and list them (API)
          </a>
        </p>
      )}
      {names.length > 0 && citations.items.length > 0 && !verdicts && (
        <div className="ai-check">
          <button type="button" onClick={judge} disabled={judging}>
            {judging ? (
              <span className="spinner" aria-hidden="true" />
            ) : (
              <span className="ai-badge" aria-hidden="true">
                AI
              </span>
            )}
            <span>{judging ? 'Reading the records…' : `Ask AI what ${names[0]} is to these trials`}</span>
          </button>
          <span className="ai-check-hint">
            {`Reads each cited record and says whether ${names[0]} is studied, given alongside, an eligibility ` +
              'condition or background, quoting the record.'}
          </span>
          {problem && <span className="ai-check-problem">{problem}</span>}
        </div>
      )}
      {verdicts && (
        <p className="muted">Roles are a language model's reading; each quote was found in the trial's record.</p>
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
              {verdicts?.[c.nct_id] && (
                <li className={`verdict ${verdicts[c.nct_id].role}`}>
                  AI: {names[0]} is {ROLES[verdicts[c.nct_id].role]}
                  {verdicts[c.nct_id].quote && (
                    <>
                      {' '}
                      — <q>{verdicts[c.nct_id].quote!.value}</q>
                    </>
                  )}
                </li>
              )}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  )
}
