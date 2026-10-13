// Answers already given in this session, so asking again shows them instantly (as chat
// assistants do) instead of planning and querying again.

import type { VisualizationResponse } from './api/types'
import type { StructuredFields } from './presets'

export interface Entry {
  key: string
  query: string
  fields: StructuredFields
  response?: VisualizationResponse
  /** An explained answer without a chart, e.g. a refusal. */
  notice?: string
}

const STORAGE_KEY = 'cheiron.history.v1'
const MAX_ENTRIES = 20

/** The same question: same words (ignoring case, spacing and a trailing "?") and same filters. */
export function entryKey(query: string, fields: StructuredFields): string {
  const text = query.toLowerCase().split(/\s+/).filter(Boolean).join(' ').replace(/[\s?]+$/, '')
  const filters = Object.entries(fields)
    .map(([name, value]) => [name, Array.isArray(value) ? [...value].sort() : value])
    .sort(([a], [b]) => String(a).localeCompare(String(b)))
  return JSON.stringify([text, filters])
}

export function remember(entries: Entry[], entry: Entry): Entry[] {
  return [entry, ...entries.filter((e) => e.key !== entry.key)].slice(0, MAX_ENTRIES)
}

// sessionStorage, not localStorage: answers reflect the registry's data of the day.
export function loadHistory(): Entry[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Entry[]) : []
  } catch {
    return []
  }
}

/** Keeps as many recent answers as the browser allows; one answer can be hundreds of KB. */
export function saveHistory(entries: Entry[]): void {
  for (let count = entries.length; count >= 0; count--) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, count)))
      return
    } catch {
      // over quota: try with fewer
    }
  }
}
