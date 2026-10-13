import { useState } from 'react'
import type { SearchOptions } from '../api/types'
import type { StructuredFields } from '../presets'
import { FilterFields } from './FilterFields'

const NAMES: Record<keyof StructuredFields, string> = {
  drug_name: 'Drug',
  condition: 'Condition',
  sponsor: 'Sponsor',
  country: 'Country',
  phases: 'Phase',
  statuses: 'Status',
  start_year: 'Started from',
  end_year: 'Started until',
  nct_id: 'Trial',
}

interface Props {
  query: string
  onQueryChange: (query: string) => void
  fields: StructuredFields
  onFieldsChange: (fields: StructuredFields) => void
  options: SearchOptions | null
  loading: boolean
  onAsk: () => void
}

/** The question box at the bottom of the page, with its filters. */
export function Composer({ query, onQueryChange, fields, onFieldsChange, options, loading, onAsk }: Props) {
  const [showFilters, setShowFilters] = useState(false)
  const active = Object.keys(fields) as (keyof StructuredFields)[]
  const codeLabel = (code: string) =>
    [...(options?.phases ?? []), ...(options?.statuses ?? [])].find((c) => c.value === code)?.label ?? code
  const shown = (key: keyof StructuredFields) => {
    const value = fields[key]
    return Array.isArray(value) ? value.map(codeLabel).join(', ') : String(value)
  }
  const remove = (key: keyof StructuredFields) => {
    const next = { ...fields }
    delete next[key]
    onFieldsChange(next)
  }

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault()
        onAsk()
      }}
    >
      {showFilters && (
        <div className="composer-filters">
          <FilterFields value={fields} onChange={onFieldsChange} options={options} />
        </div>
      )}
      {active.length > 0 && (
        <div className="active-filters">
          {active.map((key) => (
            <span key={key} className="chip on">
              <span>{`${NAMES[key]}: ${shown(key)}`}</span>
              <button type="button" aria-label={`Remove the ${NAMES[key]} filter`} onClick={() => remove(key)}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="composer-box">
        <textarea
          value={query}
          rows={1}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              onAsk()
            }
          }}
          placeholder="Ask about clinical trials…"
        />
        <div className="composer-actions">
          <button
            type="button"
            className={showFilters ? 'secondary on' : 'secondary'}
            aria-expanded={showFilters}
            onClick={() => setShowFilters(!showFilters)}
          >
            {active.length > 0 ? `Filters · ${active.length}` : 'Filters'}
          </button>
          <button className="primary" type="submit" disabled={loading || !query.trim()}>
            {loading && <span className="spinner" aria-hidden="true" />}
            <span>{loading ? 'Working…' : 'Ask'}</span>
          </button>
        </div>
      </div>
      <p className="hint">Enter to ask · Shift+Enter for a new line · filters apply to every compared group</p>
    </form>
  )
}
