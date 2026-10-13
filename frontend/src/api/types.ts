// Response schema of POST /api/plans (see README "Visualization spec").

export type ChartType =
  | 'bar_chart'
  | 'grouped_bar_chart'
  | 'time_series'
  | 'histogram'
  | 'scatter_plot'
  | 'network_graph'
  | 'stacked_bar_chart'
  | 'heatmap'
  | 'choropleth_map'
  | 'donut_chart'
  | 'line_chart'
  | 'forest_plot'

export type FieldType = 'nominal' | 'ordinal' | 'quantitative' | 'temporal'

export interface Channel {
  field: string
  type: FieldType
  title: string
  order: (string | number)[] | null
  unit: string | null
  time_unit: string | null
  /** null for a linear axis; 'symlog' for a log-like axis that keeps zeros. */
  scale: 'symlog' | null
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
  /** The evidence as one line of registered text, e.g. "phases: PHASE3". */
  excerpt: string
}

export interface Citations {
  total: number
  items: Citation[]
  /** Every contributing NCT ID, when the request sets all_citation_ids; null otherwise. */
  nct_ids: string[] | null
}

export type Row = Record<string, unknown> & { citations: Citations }

export interface NetworkNode {
  id: string
  label: string
  kind: string
  trial_count: number
  community: string | null
  anchor: boolean
  partners: number
  citations: Citations
}

export interface NetworkEdge {
  source: string
  target: string
  trial_count: number
  association: number
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
  /** Counts cover all matched trials (counted per category by the registry); citations cover the analyzed. */
  exact_counts: boolean
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

/** Another chart form of the same data, with notes about this form. */
export interface View extends Visualization {
  notes: string[]
}

export interface VisualizationResponse {
  visualization: Visualization
  alternatives: View[]
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
