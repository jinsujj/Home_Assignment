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
  /** Cohort filter terms the trial only mentions (e.g. in its description) rather than registers. */
  mentioned_only: string[]
}

export interface Citations {
  total: number
  items: Citation[]
  /** Every contributing NCT ID, when the request sets all_citation_ids; null otherwise. */
  nct_ids: string[] | null
  /** A ClinicalTrials.gov API request whose totalCount is the datum's count, when the registry counted it. */
  registry_query: string | null
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
  /** Sponsor nodes of sponsor networks: INDUSTRY, NIH, OTHER_GOV, OTHER, ... */
  sponsor_class?: string | null
  citations: Citations
}

export interface NetworkEdge {
  source: string
  target: string
  trial_count: number
  association: number
  /** Drug-drug links: trials giving both in one arm, and trials giving them only in different arms. */
  combined_trials?: number
  compared_trials?: number
  /** Sponsor links: trials the sponsor leads, and trials it collaborates on. */
  lead_trials?: number
  collaborator_trials?: number
  /** Which way dominates: combined / compared / unknown, or lead / collaborator. */
  relation?: string
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
  /** What the cohort's free-text filters are called in trial text; POST /api/mentions takes them. */
  names: string[]
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
  /** The ClinicalTrials.gov data snapshot (its /version dataTimestamp) the answer was computed from. */
  data_version: string | null
  /** For notes that count trials: those trials, cited like a datum. */
  note_citations: { note: string; citations: Citations }[]
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
  /** The compared cohort the datum belongs to, if any. */
  cohort?: string
}

export type MentionRole = 'studied' | 'given_alongside' | 'eligibility' | 'background' | 'unclear'

/** POST /api/mentions: what the filtered entity is to each trial, quoting its record. */
export interface MentionVerdict {
  nct_id: string
  role: MentionRole
  quote: Evidence | null
  passages: number
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

/** What a follow-up question refines: POST /api/visualize `context`. */
export interface Conversation {
  /** Earlier questions, oldest first (at most 5). */
  questions: string[]
  /** The plan that answered the last of them (its response's meta.plan). */
  plan: unknown
}

/** POST /api/answers: the question answered in words, and follow-ups already planned. */
export interface WrittenAnswer {
  /** Every number in a sentence was found in the data it cites; refs are JSON pointers into the response. */
  sentences: { text: string; refs: string[] }[]
  /** Sentences left out because a number in them was not in the data they cite. */
  dropped: number
  follow_ups: { query: string; interpretation: string; plan: unknown }[]
  note: string
}
