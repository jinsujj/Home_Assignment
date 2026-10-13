// Example questions covering every chart type, after the assignment's appendix.

export interface Example {
  query: string
  fields?: StructuredFields
}

export interface StructuredFields {
  drug_name?: string
  condition?: string
  sponsor?: string
  country?: string
  phases?: string[]
  statuses?: string[]
  start_year?: number
  end_year?: number
}

export const EXAMPLES: Example[] = [
  { query: 'How has the number of trials for this drug changed over time?', fields: { drug_name: 'Pembrolizumab' } },
  { query: 'How are breast cancer trials distributed across phases?' },
  { query: 'Compare phases for trials involving Keytruda vs Opdivo.' },
  { query: 'Which countries have the most recruiting trials for lung cancer?' },
  { query: 'Compare sponsor categories across asthma and COPD trials.' },
  { query: 'What are the most common intervention types for Alzheimer’s disease trials?' },
  { query: 'Which drugs frequently co-occur in combination studies for pancreatic cancer?' },
  { query: 'Show a network of sponsors and drugs for melanoma trials.' },
  { query: 'Which hospitals run pembrolizumab trials together?' },
  { query: 'How large are phase 3 obesity trials?' },
  { query: 'Do longer phase 3 pembrolizumab trials enroll more patients?' },
  { query: 'What were the results of the KEYNOTE-189 trial?' },
]
