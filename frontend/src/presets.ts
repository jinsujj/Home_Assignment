// One example plan per chart type, mirroring the assignment's example questions.

const pembrolizumab = { label: 'Pembrolizumab', filter: { intervention: 'pembrolizumab' } }

export const PRESETS: { question: string; request: unknown }[] = [
  {
    question: 'How are pembrolizumab trials distributed across phases?',
    request: { plan: { kind: 'count_by', cohorts: [pembrolizumab], dimension: 'phase' } },
  },
  {
    question: 'How many pembrolizumab trials started each year since 2015?',
    request: {
      plan: {
        kind: 'count_by',
        cohorts: [{ label: 'Pembrolizumab', filter: { intervention: 'pembrolizumab', start_year_from: 2015 } }],
        dimension: 'start_year',
      },
    },
  },
  {
    question: 'Compare phases for pembrolizumab vs nivolumab trials.',
    request: {
      plan: {
        kind: 'count_by',
        cohorts: [pembrolizumab, { label: 'Nivolumab', filter: { intervention: 'nivolumab' } }],
        dimension: 'phase',
      },
    },
  },
  {
    question: 'Which countries have the most recruiting lung cancer trials?',
    request: {
      plan: {
        kind: 'count_by',
        cohorts: [{ label: 'Lung cancer, recruiting', filter: { condition: 'lung cancer', statuses: ['RECRUITING'] } }],
        dimension: 'country',
        top_n: 12,
      },
    },
  },
  {
    question: 'Who sponsors pembrolizumab trials in each phase?',
    request: { plan: { kind: 'count_by', cohorts: [pembrolizumab], dimension: 'phase', split_by: 'lead_sponsor_class' } },
  },
  {
    question: 'Which drugs are combined with pembrolizumab?',
    request: {
      plan: { kind: 'co_occurrence', cohort: pembrolizumab, source: 'drug', target: 'drug', max_nodes: 20, min_shared_trials: 3 },
    },
  },
  {
    question: 'Network of sponsors and drugs in phase 3 breast cancer trials.',
    request: {
      plan: {
        kind: 'co_occurrence',
        cohort: { label: 'Breast cancer, phase 3', filter: { condition: 'breast cancer', phases: ['PHASE3'] } },
        source: 'sponsor',
        target: 'drug',
        max_nodes: 24,
        min_shared_trials: 2,
      },
    },
  },
  {
    question: 'Which sites run pembrolizumab trials together?',
    request: {
      plan: { kind: 'co_occurrence', cohort: pembrolizumab, source: 'site', target: 'site', max_nodes: 16, min_shared_trials: 8 },
    },
  },
  {
    question: 'How large are pembrolizumab trials?',
    request: { plan: { kind: 'distribution', cohort: pembrolizumab, measure: 'enrollment' } },
  },
  {
    question: 'Do longer phase 3 pembrolizumab trials enroll more patients?',
    request: {
      plan: {
        kind: 'correlation',
        cohort: { label: 'Pembrolizumab, phase 3', filter: { intervention: 'pembrolizumab', phases: ['PHASE3'] } },
        x: 'duration_months',
        y: 'enrollment',
      },
    },
  },
]
