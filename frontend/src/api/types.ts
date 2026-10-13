// Response schema of POST /api/plans (see README "Visualization spec").

export type ChartType =
  | 'bar_chart'
  | 'grouped_bar_chart'
  | 'time_series'
  | 'histogram'
  | 'scatter_plot'
  | 'network_graph'

export type FieldType = 'nominal' | 'ordinal' | 'quantitative' | 'temporal'

export interface Channel {
  field: string
  type: FieldType
  title: string
  order: (string | number)[] | null
  unit: string | null
  time_unit: string | null
}

export interface Evidence {
  field: string
  value: string
}

export interface Citation {
  nct_id: string
  title: string
  url: string
  evidence: Evidence[]
}

export interface Citations {
  total: number
  items: Citation[]
}

export type Row = Record<string, unknown> & { citations: Citations }

export interface NetworkNode {
  id: string
  label: string
  kind: string
  trial_count: number
  citations: Citations
}

export interface NetworkEdge {
  source: string
  target: string
  trial_count: number
  citations: Citations
}

export interface NetworkData {
  nodes: NetworkNode[]
  edges: NetworkEdge[]
}

export interface Visualization {
  type: ChartType
  title: string
  encoding: Record<string, Channel>
  data: Row[] | NetworkData
}

export interface CohortMeta {
  label: string
  matched: number
  analyzed: number
  truncated: boolean
}

export interface TrialOption {
  nct_id: string
  title: string
  url: string
  enrollment: number | null
}

export interface TrialMeta extends TrialOption {
  alternatives: TrialOption[]
}

export interface Meta {
  source: string
  query: string | null
  interpretation: string | null
  plan: unknown
  cohorts: CohortMeta[]
  trial: TrialMeta | null
  notes: string[]
}

export interface VisualizationResponse {
  visualization: Visualization
  meta: Meta
}

/** A datum the user clicked, with the trials behind it. */
export interface Selection {
  label: string
  count: number
  citations: Citations
}

/** GET /api/options */
export interface Choice {
  value: string
  label: string
  trials: number | null
}

export interface SearchOptions {
  countries: Choice[]
  conditions: Choice[]
  interventions: Choice[]
  sponsors: Choice[]
  phases: Choice[]
  statuses: Choice[]
}
