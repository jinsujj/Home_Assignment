import { useState } from 'react'
import type { Selection, WrittenAnswer } from '../api/types'

interface Props {
  answer: WrittenAnswer | null
  writing: boolean
  problem: string | null
  /** The data a sentence cites, as the citation panel shows it; null when it has no trials. */
  resolve: (pointer: string) => Selection | null
  onSelect: (selection: Selection) => void
  /** Asks a planned follow-up question. */
  onFollowUp: (query: string) => void
  busy: boolean
}

/** The question answered in words, each sentence opening the data it cites, and what to ask next. */
export function AnswerPanel({ answer, writing, problem, resolve, onSelect, onFollowUp, busy }: Props) {
  const [opened, setOpened] = useState<number | null>(null)

  if (writing) {
    return (
      <p className="answer muted">
        <span className="spinner" aria-hidden="true" />
        <span>Writing a short answer from the data…</span>
      </p>
    )
  }
  if (problem) return <p className="answer muted">{`No written answer: ${problem}`}</p>
  if (!answer) return null

  const sources = answer.sentences.map((s) => s.refs.map(resolve).filter((x): x is Selection => x !== null))
  return (
    <div className="answer">
      {answer.sentences.length > 0 ? (
        <p>
          {answer.sentences.map((sentence, i) => (
            <span key={sentence.text}>
              <span>{sentence.text}</span>{' '}
              {sources[i].length > 0 && (
                <button
                  type="button"
                  className={opened === i ? 'sources on' : 'sources'}
                  aria-expanded={opened === i}
                  onClick={() => setOpened(opened === i ? null : i)}
                >
                  {sources[i].length === 1 ? '1 source' : `${sources[i].length} sources`}
                </button>
              )}{' '}
            </span>
          ))}
        </p>
      ) : (
        <p className="muted">No sentence could be checked against the data; the chart below is the answer.</p>
      )}
      {opened !== null && (
        <div className="source-list">
          {sources[opened].map((source) => (
            <button key={source.label} type="button" className="chip" onClick={() => onSelect(source)}>
              {source.label.length > 70 ? `${source.label.slice(0, 67)}…` : source.label}
            </button>
          ))}
        </div>
      )}
      <p className="answer-note">
        {"Written by a language model from this chart's data; every number was found in the data its sentence cites." +
          (answer.dropped ? ` ${answer.dropped} more ${answer.dropped === 1 ? 'sentence was' : 'sentences were'} left out: a number in them was not.` : '')}
      </p>
      {answer.follow_ups.length > 0 && (
        <div className="follow-ups">
          <span className="muted">Ask next:</span>
          {answer.follow_ups.map((f) => (
            <button key={f.query} type="button" className="chip" title={f.interpretation} disabled={busy} onClick={() => onFollowUp(f.query)}>
              {f.query}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
