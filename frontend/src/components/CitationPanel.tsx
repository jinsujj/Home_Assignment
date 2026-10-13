import { useState } from 'react'
import { judgeMentions } from '../api/client'
import type { Citations, MentionRole, MentionVerdict, Selection } from '../api/types'

const ROLES: Record<MentionRole, string> = {
  studied: 'studied by the trial',
  given_alongside: 'given alongside what the trial tests',
  eligibility: 'an eligibility condition',
  background: 'background only',
  unclear: 'unclear',
}

/** Trials listed per step beyond the five cited in full. */
const PAGE = 20
/** POST /api/mentions judges at most 10 trials per request. */
const JUDGE_BATCH = 10

function Verdict({ verdict, name }: { verdict: MentionVerdict; name: string }) {
  return (
    <li className={`verdict ${verdict.role}`}>
      <span>{`AI: ${name} is ${ROLES[verdict.role]}`}</span>
      {verdict.quote && (
        <>
          <span>{' — '}</span>
          <q>{verdict.quote.value}</q>
        </>
      )}
    </li>
  )
}

interface Props {
  selection: Selection | null
  /** What the cohort's filtered entity is called; empty when the cohort has no text filter. */
  names: string[]
  /** Every trial behind the citations, beyond those cited in full; null when they cannot be listed. */
  listTrials?: (citations: Citations) => Promise<string[]> | null
}

export function CitationPanel({ selection, names, listTrials }: Props) {
  const [verdicts, setVerdicts] = useState<Record<string, MentionVerdict>>({})
  const [judging, setJudging] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [others, setOthers] = useState<string[] | null>(null)
  const [shown, setShown] = useState(PAGE)
  const [listing, setListing] = useState(false)
  const [listProblem, setListProblem] = useState<string | null>(null)

  if (!selection) {
    return <p className="hint">Click a bar, point, node or link to see the trials behind it.</p>
  }
  const { label, count, citations } = selection

  const listed = [...citations.items.map((c) => c.nct_id), ...(others ?? []).slice(0, shown)]
  // Only the trials on screen that were not judged yet, so listing more never re-reads the rest.
  const unjudged = listed.filter((id) => !verdicts[id])

  const judge = () => {
    setJudging(true)
    setProblem(null)
    const batches = []
    for (let i = 0; i < unjudged.length; i += JUDGE_BATCH) batches.push(unjudged.slice(i, i + JUDGE_BATCH))
    Promise.all(batches.map((batch) => judgeMentions(batch, names)))
      .then((found) =>
        setVerdicts((known) => ({ ...known, ...Object.fromEntries(found.flat().map((v) => [v.nct_id, v])) })),
      )
      .catch((e: unknown) => setProblem(e instanceof Error ? e.message : String(e)))
      .finally(() => setJudging(false))
  }

  const listOthers = () => {
    const found = listTrials?.(citations)
    if (!found) return
    setListing(true)
    setListProblem(null)
    const cited = new Set(citations.items.map((c) => c.nct_id))
    found
      .then((ids) => setOthers(ids.filter((id) => !cited.has(id))))
      .catch((e: unknown) => setListProblem(e instanceof Error ? e.message : String(e)))
      .finally(() => setListing(false))
  }

  const judged = Object.keys(verdicts).length > 0
  const aiCheck = names.length > 0 && unjudged.length > 0 && (
    <div className="ai-check">
      <button type="button" onClick={judge} disabled={judging}>
        {judging ? (
          <span className="spinner" aria-hidden="true" />
        ) : (
          <span className="ai-badge" aria-hidden="true">
            AI
          </span>
        )}
        <span>
          {judging
            ? `Reading ${unjudged.length} records…`
            : judged
              ? `Ask AI about the ${unjudged.length} trials not checked yet`
              : `Ask AI what ${names[0]} is to these trials`}
        </span>
      </button>
      <span className="ai-check-hint">
        {`Reads each listed record and says whether ${names[0]} is studied, given alongside, an eligibility ` +
          'condition or background, quoting the record.'}
      </span>
      {problem && <span className="ai-check-problem">{problem}</span>}
    </div>
  )

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
      {!others && aiCheck}
      {judged && (
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
              {verdicts[c.nct_id] && <Verdict verdict={verdicts[c.nct_id]} name={names[0]} />}
            </ul>
          </li>
        ))}
      </ul>
      {citations.items.length < Math.max(citations.total, count) && listTrials && !others && (
        <p>
          <button type="button" className="link" onClick={listOthers} disabled={listing}>
            {listing && <span className="spinner" aria-hidden="true" />}
            <span>{listing ? 'Listing the trials…' : 'List the other trials'}</span>
          </button>
          {listProblem && <span className="ai-check-problem">{listProblem}</span>}
        </p>
      )}
      {others && (
        <div className="other-trials">
          <p className="muted">
            {others.length === 0
              ? 'No other trials could be listed; the API link above lists them.'
              : `${Math.min(shown, others.length).toLocaleString()} of ${others.length.toLocaleString()} more trials, by NCT ID:`}
          </p>
          <ul className="other-ids">
            {others.slice(0, shown).map((id) => (
              <li key={id} className={verdicts[id] ? 'judged' : undefined}>
                <a href={`https://clinicaltrials.gov/study/${id}`} target="_blank" rel="noreferrer">
                  {id}
                </a>
                {verdicts[id] && (
                  <ul>
                    <Verdict verdict={verdicts[id]} name={names[0]} />
                  </ul>
                )}
              </li>
            ))}
          </ul>
          {shown < others.length && (
            <button type="button" className="link" onClick={() => setShown(shown + PAGE)}>
              {`Show ${Math.min(PAGE, others.length - shown)} more`}
            </button>
          )}
          {aiCheck}
        </div>
      )}
    </div>
  )
}
