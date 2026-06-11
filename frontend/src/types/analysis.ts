export interface Project {
  id: string
  name: string
  description: string
  is_default: boolean
  created_at: string
}

export interface AnalysisFinding {
  resource_name: string
  resource_type: string
  severity: 'high' | 'medium' | 'low'
  issue: string
  monthly_savings: string
  annual_savings: string
  recommendation: string
  remediation_steps: string[]
}

export interface AnalysisSummary {
  total_resources: number
  issues_found: number
  estimated_monthly_savings: string
  estimated_annual_savings: string
}

export interface AIAnalysis {
  summary: AnalysisSummary
  findings: AnalysisFinding[]
}

export interface AnalysisResult {
  analysis_id: string
  project_id: string
  project_name: string
  resources: Record<string, unknown>[]
  resource_count: Record<string, number>
  ai_analysis: AIAnalysis | null
  mock?: boolean
  input_tokens: number
  output_tokens: number
  timestamp: string
  model_used?: string
  analysis_mode?: string
  failure_reason?: string
}

export interface HistoryItem {
  id: string
  project_id: string
  project_name: string
  resources_scanned: number
  issues_found: number
  estimated_monthly_savings: string
  estimated_annual_savings: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  created_at: string
  run_by?: string
  model_used?: string
  analysis_mode?: string
  failure_reason?: string
}

export interface ProgressMessage {
  stage: number
  total_stages: number
  progress_pct: number
  message: string
  status: 'running' | 'completed' | 'failed'
}

export type AnalysisStatus = 'idle' | 'scanning' | 'complete' | 'error'
