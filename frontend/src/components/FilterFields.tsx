import type { Choice, SearchOptions } from '../api/types'
import type { StructuredFields } from '../presets'

interface Props {
  value: StructuredFields
  onChange: (value: StructuredFields) => void
  options: SearchOptions | null
}

type TextKey = 'drug_name' | 'condition' | 'sponsor'
type ListKey = 'phases' | 'statuses'
type YearKey = 'start_year' | 'end_year'

const THIS_YEAR = new Date().getFullYear()
const YEARS = Array.from({ length: THIS_YEAR + 3 - 1999 }, (_, i) => THIS_YEAR + 2 - i)

/** Structured request fields, chosen rather than typed wherever the registry has a fixed list. */
export function FilterFields({ value, onChange, options }: Props) {
  const set = (patch: StructuredFields) => {
    const next: Record<string, unknown> = { ...value, ...patch }
    for (const key of Object.keys(next)) {
      const v = next[key]
      if (v === undefined || v === '' || (Array.isArray(v) && v.length === 0)) delete next[key]
    }
    onChange(next as StructuredFields)
  }

  const text = (key: TextKey, label: string, suggestions: Choice[] | undefined, placeholder: string) => (
    <label>
      {label}
      <input
        list={`${key}-suggestions`}
        value={value[key] ?? ''}
        placeholder={placeholder}
        onChange={(e) => set({ [key]: e.target.value })}
      />
      <datalist id={`${key}-suggestions`}>
        {suggestions?.map((c) => (
          <option key={c.value} value={c.value} />
        ))}
      </datalist>
    </label>
  )

  const chips = (key: ListKey, label: string, choices: Choice[] | undefined) => {
    const selected = value[key] ?? []
    const toggle = (code: string) =>
      set({ [key]: selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code] })
    return (
      <fieldset>
        <legend>{label}</legend>
        <div className="chips">
          {choices?.map((c) => (
            <button
              key={c.value}
              type="button"
              className={selected.includes(c.value) ? 'chip on' : 'chip'}
              aria-pressed={selected.includes(c.value)}
              onClick={() => toggle(c.value)}
            >
              {c.label}
            </button>
          ))}
        </div>
      </fieldset>
    )
  }

  const year = (key: YearKey, label: string) => (
    <label>
      {label}
      <select value={value[key] ?? ''} onChange={(e) => set({ [key]: e.target.value ? Number(e.target.value) : undefined })}>
        <option value="">Any</option>
        {YEARS.map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>
    </label>
  )

  const countries = options?.countries ?? []
  const unlisted = value.country && !countries.some((c) => c.value === value.country)

  return (
    <div className="filter-fields">
      {text('drug_name', 'Drug', options?.interventions, 'e.g. Pembrolizumab')}
      {text('condition', 'Condition', options?.conditions, 'e.g. Breast Cancer')}
      {text('sponsor', 'Sponsor', options?.sponsors, 'e.g. Pfizer')}
      <label>
        Country
        <select value={value.country ?? ''} onChange={(e) => set({ country: e.target.value })}>
          <option value="">Any country</option>
          {unlisted && <option value={value.country}>{value.country}</option>}
          {countries.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label} ({c.trials?.toLocaleString()})
            </option>
          ))}
        </select>
      </label>
      {chips('phases', 'Phase', options?.phases)}
      {chips('statuses', 'Status', options?.statuses)}
      <div className="years">
        {year('start_year', 'Started from')}
        {year('end_year', 'to')}
      </div>
      <label>
        Trial
        <input
          value={value.nct_id ?? ''}
          placeholder="NCT ID, for one trial's results"
          pattern="NCT\d{8}"
          onChange={(e) => set({ nct_id: e.target.value.trim().toUpperCase() })}
        />
      </label>
      {Object.keys(value).length > 0 && (
        <button type="button" className="link" onClick={() => onChange({})}>
          Clear filters
        </button>
      )}
    </div>
  )
}
