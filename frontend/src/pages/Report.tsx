import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Navbar from '../components/Navbar'
import SummaryCards from '../components/SummaryCards'
import FindingsTable from '../components/FindingsTable'
import MockBanner from '../components/MockBanner'
import TokenUsage from '../components/TokenUsage'
import api from '../services/api'
import type { AnalysisResult } from '../types/analysis'

function Spinner() {
  return (
    <div className="flex items-center justify-center py-24">
      <svg className="animate-spin w-8 h-8 text-blue-500" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
      </svg>
    </div>
  )
}

export default function Report() {
  const { id } = useParams<{ id: string }>()
  const [report, setReport] = useState<AnalysisResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return

    // Try localStorage first (fresh analysis from Dashboard)
    const cached = localStorage.getItem(`analysis_${id}`)
    if (cached) {
      try {
        setReport(JSON.parse(cached))
        setLoading(false)
        return
      } catch {
        // fall through to API
      }
    }

    // Fetch from backend (coming from History page)
    api.get<AnalysisResult>(`/analysis/${id}`)
      .then(({ data }) => setReport(data))
      .catch(() => setError('Analysis not found or unavailable.'))
      .finally(() => setLoading(false))
  }, [id])

  const formatDate = (ts: string) =>
    new Date(ts).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    })

  if (loading) return <div className="min-h-screen bg-slate-950"><Navbar /><Spinner /></div>

  if (error || !report) {
    return (
      <div className="min-h-screen bg-slate-950">
        <Navbar />
        <div className="max-w-5xl mx-auto px-4 py-16 text-center">
          <p className="text-2xl font-bold text-slate-300 mb-2">Report Not Found</p>
          <p className="text-slate-400 mb-6">{error}</p>
          <Link to="/history" className="btn-primary">Back to History</Link>
        </div>
      </div>
    )
  }

  const ai = report.ai_analysis

  const MODE_LABELS: Record<string, string> = {
    fast: '⚡ Fast',
    balanced: '🧠 Balanced',
    deep: '🔍 Deep Analysis',
  }
  const modelShort = (id: string) => {
    if (id.includes('haiku')) return 'Claude Haiku'
    if (id.includes('sonnet')) return 'Claude Sonnet'
    if (id.includes('opus')) return 'Claude Opus'
    return id
  }

  return (
    <div className="min-h-screen bg-slate-950">
      <Navbar />

      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Link to="/history" className="text-slate-500 hover:text-slate-300 text-sm transition-colors">
                ← History
              </Link>
            </div>
            <h1 className="text-2xl font-bold text-slate-100">
              {report.project_name}
            </h1>
            <p className="text-sm text-slate-400 mt-0.5">
              Analysis Report · {formatDate(report.timestamp)}
            </p>
            {(report.analysis_mode || report.model_used) && (
              <div className="flex flex-wrap items-center gap-2 mt-2">
                {report.analysis_mode && (
                  <span className="bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-medium px-2 py-0.5 rounded-full">
                    {MODE_LABELS[report.analysis_mode] ?? report.analysis_mode}
                  </span>
                )}
                {report.model_used && (
                  <span className="bg-slate-700/50 border border-slate-600 text-slate-400 text-xs font-medium px-2 py-0.5 rounded-full">
                    {modelShort(report.model_used)}
                  </span>
                )}
              </div>
            )}
          </div>
          <span className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-medium px-2.5 py-1 rounded-full shrink-0">
            Completed
          </span>
        </div>

        {/* Mock banner */}
        {report.mock && <MockBanner />}

        {/* Token Usage */}
        {(report.input_tokens > 0 || report.output_tokens > 0) && (
          <TokenUsage inputTokens={report.input_tokens} outputTokens={report.output_tokens} />
        )}

        {/* Executive Summary */}
        {ai ? (
          <>
            <div>
              <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Executive Summary
              </h2>
              <SummaryCards summary={ai.summary} />
            </div>

            {/* Savings highlight */}
            {ai.summary.issues_found > 0 && (
              <div className="card p-5 bg-gradient-to-r from-emerald-500/5 to-blue-500/5 border-emerald-500/20">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center shrink-0">
                    <svg className="w-5 h-5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                  <div>
                    <p className="font-semibold text-slate-100">
                      Potential savings of{' '}
                      <span className="text-emerald-400">{ai.summary.estimated_annual_savings}</span> per year
                    </p>
                    <p className="text-sm text-slate-400 mt-0.5">
                      {ai.summary.estimated_monthly_savings}/month across {ai.summary.issues_found} identified issues
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Findings */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
                  Findings ({ai.findings.length})
                </h2>
                <div className="flex gap-2 text-xs">
                  {['high', 'medium', 'low'].map((sev) => {
                    const count = ai.findings.filter((f) => f.severity === sev).length
                    if (!count) return null
                    return (
                      <span key={sev}
                        className={sev === 'high' ? 'badge-high' : sev === 'medium' ? 'badge-medium' : 'badge-low'}>
                        {count} {sev}
                      </span>
                    )
                  })}
                </div>
              </div>
              <FindingsTable findings={ai.findings} />
            </div>
          </>
        ) : (
          <div className="card p-10 text-center">
            <p className="text-slate-300 font-medium">AI Analysis Unavailable</p>
            <p className="text-sm text-slate-500 mt-1">
              Resources were scanned but Claude AI analysis failed for this report.
            </p>
            <p className="text-xs text-slate-600 mt-3">
              {Object.values(report.resource_count).reduce((a, b) => a + b, 0)} resources collected
            </p>
          </div>
        )}
      </main>
    </div>
  )
}
