import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import ProgressTracker from '../components/ProgressTracker'
import SummaryCards from '../components/SummaryCards'
import MockBanner from '../components/MockBanner'
import AnalysisModeSelector from '../components/AnalysisModeSelector'
import api from '../services/api'
import { authService } from '../services/auth'
import type { AnalysisResult, AnalysisStatus, HistoryItem, MonitoringCoverageData, MonitoringDropletItem, Project } from '../types/analysis'

// ── Helpers ────────────────────────────────────────────────────────────────────

function parseDollars(s: string): number {
  return parseFloat(s.replace(/[^0-9.]/g, '')) || 0
}

function formatDollars(n: number): string {
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}k`
  return `$${n.toFixed(0)}`
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function AggregateStat({
  label,
  value,
  color,
  icon,
}: {
  label: string
  value: string
  color: string
  icon: React.ReactNode
}) {
  return (
    <div className="card p-4">
      <div className={`inline-flex p-2 rounded-lg border mb-3 ${color}`}>{icon}</div>
      <p className="text-xl font-bold text-slate-100">{value}</p>
      <p className="text-xs text-slate-400 mt-0.5">{label}</p>
    </div>
  )
}

function RecentAnalyses({ items }: { items: HistoryItem[] }) {
  const navigate = useNavigate()
  const formatDate = (ts: string) =>
    new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
        <h2 className="text-sm font-semibold text-slate-100">Recent Analyses</h2>
        <Link to="/history" className="text-xs text-blue-400 hover:text-blue-300 transition-colors">
          View all →
        </Link>
      </div>
      <div className="divide-y divide-slate-700/40">
        {items.map((item) => (
          <button
            key={item.id}
            onClick={() => navigate(`/report/${item.id}`)}
            className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-slate-700/30 transition-colors group"
          >
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-100 group-hover:text-blue-400 transition-colors truncate">
                {item.project_name}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                {formatDate(item.created_at)}
                {item.run_by && (
                  <span className="ml-1.5 text-slate-600">· {item.run_by}</span>
                )}
              </p>
            </div>
            <div className="text-right shrink-0">
              {item.issues_found > 0 ? (
                <>
                  <p className="text-xs font-medium text-amber-400">{item.issues_found} issues</p>
                  <p className="text-xs text-emerald-400 mt-0.5">{item.estimated_monthly_savings}/mo</p>
                </>
              ) : (
                <p className="text-xs text-slate-500">No issues</p>
              )}
            </div>
            <svg className="w-4 h-4 text-slate-600 group-hover:text-slate-400 shrink-0 transition-colors"
              fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Fleet Health sub-components ───────────────────────────────────────────────

const ENV_STYLES: Record<string, string> = {
  PROD:    'bg-rose-500/15 border-rose-500/30 text-rose-400',
  STAGING: 'bg-orange-500/15 border-orange-500/30 text-orange-400',
  QA:      'bg-amber-500/15 border-amber-500/30 text-amber-400',
  DEV:     'bg-slate-700/60 border-slate-600/40 text-slate-400',
}

function EnvBadge({ env }: { env: string }) {
  const cls = ENV_STYLES[env] ?? 'bg-slate-700/60 border-slate-600/40 text-slate-500'
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium border ${cls}`}>
      {env === 'unknown' ? '—' : env}
    </span>
  )
}

function AgentBadge({ status }: { status: string }) {
  if (status === 'enabled') {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
        On
      </span>
    )
  }
  if (status === 'missing') {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-red-400">
        <span className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" />
        Missing
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-amber-400">
      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
      Unknown
    </span>
  )
}

function MetricCell({
  value,
  warnAt,
  critAt,
}: {
  value: number | null | undefined
  warnAt: number
  critAt: number
}) {
  if (value == null) return <span className="text-slate-600 text-xs">—</span>
  const pct = Math.round(value)
  let cls = 'text-slate-400'
  if (pct >= critAt) cls = 'text-red-400 font-medium'
  else if (pct >= warnAt) cls = 'text-amber-400'
  return <span className={`text-xs tabular-nums ${cls}`}>{pct}%</span>
}

function fleetSortKey(d: MonitoringDropletItem): number {
  const disk    = d.disk_percent    ?? 0
  const mem     = d.memory_percent  ?? 0
  const isProd  = d.environment === 'PROD'
  const missing = d.monitoring_status === 'missing'

  if (isProd && (disk > 85 || mem > 90)) return 0  // PROD + critical metric
  if (disk > 85)                          return 1  // high disk — hard-fail risk
  if (isProd && missing)                  return 2  // PROD with no visibility
  if (mem > 90)                           return 3  // high memory
  if (missing)                            return 4  // no visibility
  if (mem > 75 || disk > 70)             return 5  // elevated but not critical
  if (d.monitoring_status === 'unknown')  return 6  // uncertain
  return 7                                          // healthy
}

function sortedFleetDroplets(droplets: MonitoringDropletItem[]): MonitoringDropletItem[] {
  return [...droplets].sort((a, b) => {
    const diff = fleetSortKey(a) - fleetSortKey(b)
    return diff !== 0 ? diff : a.droplet_name.localeCompare(b.droplet_name)
  })
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProject, setSelectedProject] = useState<string>('')
  const [analysisMode, setAnalysisMode] = useState<string>('balanced')
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatus>('idle')
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [error, setError] = useState<string>('')
  const [loadingProjects, setLoadingProjects] = useState(true)

  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([])
  const [loadingHistory, setLoadingHistory] = useState(true)

  const [monitoringData, setMonitoringData] = useState<MonitoringCoverageData | null>(null)
  const [monitoringLoading, setMonitoringLoading] = useState(false)
  const [monitoringError, setMonitoringError] = useState('')

  const analysisRef = useRef<AbortController | null>(null)
  const navigate = useNavigate()

  // Fetch project list
  useEffect(() => {
    api.get<{ projects: Project[]; count: number }>('/projects')
      .then(({ data }) => {
        setProjects(data.projects)
        if (data.projects.length > 0) setSelectedProject(data.projects[0].id)
      })
      .catch(() => setError('Failed to load projects. Check your DigitalOcean token.'))
      .finally(() => setLoadingProjects(false))
  }, [])

  // Fetch history for stats + recent panel
  useEffect(() => {
    api.get<{ analyses: HistoryItem[]; count: number }>('/history')
      .then(({ data }) => setHistoryItems(data.analyses))
      .catch(() => {/* non-critical */})
      .finally(() => setLoadingHistory(false))
  }, [])

  // Refresh history after a new analysis completes
  const refreshHistory = useCallback(() => {
    api.get<{ analyses: HistoryItem[]; count: number }>('/history')
      .then(({ data }) => setHistoryItems(data.analyses))
      .catch(() => {})
  }, [])

  // Stable callback for ProgressTracker's onError prop.
  // Using useCallback ensures a consistent function identity across renders so
  // that even if ProgressTracker's useEffect still listed it as a dependency,
  // the WebSocket would not reconnect on unrelated Dashboard state changes.
  const handleWsError = useCallback((msg: string) => {
    setError(msg)
    setAnalysisStatus('error')
  }, [])

  const handleRunAnalysis = useCallback(async () => {
    if (!selectedProject) return
    setError('')
    setResult(null)

    analysisRef.current = new AbortController()

    try {
      // Obtain a server-generated analysis ID before opening the WebSocket so
      // progress messages are routed to the correct channel.
      const { data: reserveData } = await api.post<{ analysis_id: string }>(
        '/analyze/reserve',
        {},
        { signal: analysisRef.current.signal },
      )
      const id = reserveData.analysis_id

      setAnalysisId(id)
      setAnalysisStatus('scanning')

      const { data } = await api.post<AnalysisResult>(
        '/analyze',
        { project_id: selectedProject, reserved_id: id, analysis_mode: analysisMode },
        { signal: analysisRef.current.signal },
      )
      setResult(data)
      localStorage.setItem(`analysis_${data.analysis_id}`, JSON.stringify(data))
      setAnalysisStatus('complete')
      refreshHistory()
    } catch (err: unknown) {
      if ((err as { name?: string }).name === 'CanceledError') return
      const detail = (err as { response?: { data?: { detail?: string } } })
        .response?.data?.detail
      setError(detail ?? 'Analysis failed. Please try again.')
      setAnalysisStatus('error')
    }
  }, [selectedProject, analysisMode, refreshHistory])

  // Aggregate stats from completed analyses only.
  // Deduplicate by project_id (keep latest per project) so re-running the same
  // project without fixing anything doesn't inflate the savings totals.
  const stats = useMemo(() => {
    const completed = historyItems.filter((i) => i.status === 'completed')

    const latestPerProject = completed.reduce((map, item) => {
      const existing = map.get(item.project_id)
      if (!existing || item.created_at > existing.created_at) map.set(item.project_id, item)
      return map
    }, new Map<string, HistoryItem>())
    const unique = Array.from(latestPerProject.values())

    return {
      totalAnalyses: completed.length,
      totalFindings: unique.reduce((s, i) => s + i.issues_found, 0),
      totalMonthly: formatDollars(unique.reduce((s, i) => s + parseDollars(i.estimated_monthly_savings), 0)),
      totalAnnual:  formatDollars(unique.reduce((s, i) => s + parseDollars(i.estimated_annual_savings), 0)),
    }
  }, [historyItems])

  const recentCompleted = useMemo(
    () => historyItems.filter((i) => i.status === 'completed').slice(0, 5),
    [historyItems],
  )

  const handleScanMonitoring = useCallback(async () => {
    if (!selectedProject) return
    setMonitoringLoading(true)
    setMonitoringError('')
    setMonitoringData(null)
    try {
      const { data } = await api.get<MonitoringCoverageData>(
        `/monitoring-coverage?project_id=${encodeURIComponent(selectedProject)}`
      )
      setMonitoringData(data)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setMonitoringError(detail ?? 'Failed to scan fleet health.')
    } finally {
      setMonitoringLoading(false)
    }
  }, [selectedProject])

  const projectName = projects.find((p) => p.id === selectedProject)?.name ?? ''

  const iconServer = (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
        d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2" />
    </svg>
  )
  const iconAlert = (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
        d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
    </svg>
  )
  const iconMoney = (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
        d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
  const iconTrend = (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
    </svg>
  )

  return (
    <div className="min-h-screen bg-slate-950">
      <Navbar />

      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Dashboard</h1>
            <p className="text-sm text-slate-400 mt-1">
              Detect cloud waste and optimize your DigitalOcean spend.
            </p>
          </div>
          <Link to="/history" className="btn-ghost text-sm hidden sm:flex items-center gap-1.5">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            View History
          </Link>
        </div>

        {/* Aggregate stats — only shown once at least one analysis completed */}
        {!loadingHistory && stats.totalAnalyses > 0 && (
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
              Savings potential · latest scan per project · {stats.totalAnalyses} {stats.totalAnalyses === 1 ? 'run' : 'runs'} total
            </p>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <AggregateStat label="Analyses Run" value={stats.totalAnalyses.toString()}
                color="text-blue-400 bg-blue-500/10 border-blue-500/20" icon={iconServer} />
              <AggregateStat label="Total Findings" value={stats.totalFindings.toString()}
                color="text-red-400 bg-red-500/10 border-red-500/20" icon={iconAlert} />
              <AggregateStat label="Monthly Savings" value={stats.totalMonthly}
                color="text-emerald-400 bg-emerald-500/10 border-emerald-500/20" icon={iconMoney} />
              <AggregateStat label="Annual Savings" value={stats.totalAnnual}
                color="text-blue-400 bg-blue-500/10 border-blue-500/20" icon={iconTrend} />
            </div>
          </div>
        )}

        {/* Control panel */}
        <div className="card p-5">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1">
              <label className="block text-xs font-medium text-slate-400 mb-1.5">
                DigitalOcean Project
              </label>
              {loadingProjects ? (
                <div className="input-field flex items-center gap-2 text-slate-500">
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                  </svg>
                  Loading projects...
                </div>
              ) : projects.length === 0 ? (
                <div className="input-field text-slate-500">No projects found</div>
              ) : (
                <select
                  className="input-field"
                  value={selectedProject}
                  onChange={(e) => setSelectedProject(e.target.value)}
                  disabled={analysisStatus === 'scanning'}
                >
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              )}
            </div>

            </div>{/* end sm:flex-row */}

            <AnalysisModeSelector
              value={analysisMode}
              onChange={setAnalysisMode}
              disabled={analysisStatus === 'scanning'}
            />

            <div className="sm:self-end">
              <button
                onClick={handleRunAnalysis}
                disabled={!selectedProject || analysisStatus === 'scanning' || loadingProjects}
                className="btn-primary px-6 py-2.5 flex items-center gap-2 whitespace-nowrap"
              >
                {analysisStatus === 'scanning' ? (
                  <>
                    <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                    </svg>
                    Analyzing...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    Run Analysis
                  </>
                )}
              </button>
            </div>
          </div>

          {error && (
            <div className="mt-4 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          )}
        </div>

        {/* Progress tracker */}
        {analysisStatus === 'scanning' && analysisId && (
          <ProgressTracker
            analysisId={analysisId}
            token={authService.getToken() ?? undefined}
            onError={handleWsError}
          />
        )}

        {/* Results preview */}
        {analysisStatus === 'complete' && result?.ai_analysis && (
          <div className="space-y-4 animate-slide-up">
            {result.mock && <MockBanner />}
            <SummaryCards summary={result.ai_analysis.summary} />

            <div className="card p-5">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="font-semibold text-slate-100">
                    {result.ai_analysis.summary.issues_found} Issues Found
                  </h2>
                  <p className="text-xs text-slate-400 mt-0.5">
                    in project <span className="text-slate-300">{projectName}</span>
                  </p>
                </div>
                <button
                  onClick={() => navigate(`/report/${result.analysis_id}`)}
                  className="btn-primary flex items-center gap-1.5 text-sm"
                >
                  View Full Report
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
                  </svg>
                </button>
              </div>

              {result.ai_analysis.findings.slice(0, 3).map((f, i) => (
                <div key={i} className="flex items-center gap-3 py-2.5 border-t border-slate-700/50">
                  <span className="text-sm">
                    {f.severity === 'high' ? '🔴' : f.severity === 'medium' ? '🟡' : '🔵'}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-200 font-medium truncate">{f.resource_name}</p>
                    <p className="text-xs text-slate-400 truncate">{f.issue}</p>
                  </div>
                  <span className="text-sm text-emerald-400 font-medium shrink-0">{f.monthly_savings}</span>
                </div>
              ))}

              {result.ai_analysis.findings.length > 3 && (
                <p className="text-xs text-slate-500 text-center mt-3">
                  +{result.ai_analysis.findings.length - 3} more in the full report
                </p>
              )}
            </div>
          </div>
        )}

        {/* Unexpected: API returned success but no AI analysis data */}
        {analysisStatus === 'complete' && !result?.ai_analysis && (
          <div className="card p-8 text-center">
            <p className="text-slate-300 font-medium">Analysis completed without AI results</p>
            <p className="text-sm text-slate-500 mt-1">
              {result?.failure_reason ?? 'AI analysis did not produce results. Check the backend logs for details.'}
            </p>
            {result && (
              <button
                onClick={() => navigate(`/report/${result.analysis_id}`)}
                className="btn-ghost mt-4 text-sm"
              >
                View Report
              </button>
            )}
          </div>
        )}

        {/* Recent analyses — shown when idle and there's history */}
        {analysisStatus === 'idle' && recentCompleted.length > 0 && (
          <RecentAnalyses items={recentCompleted} />
        )}

        {/* First-run empty state */}
        {analysisStatus === 'idle' && !loadingHistory && historyItems.length === 0 && (
          <div className="card p-12 text-center">
            <div className="w-12 h-12 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <p className="font-semibold text-slate-200">No analyses yet</p>
            <p className="text-sm text-slate-400 mt-1">
              Select a project above and click <strong className="text-slate-300">Run Analysis</strong> to get started.
            </p>
          </div>
        )}

        {/* Fleet Health — always visible; scan is triggered manually */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-slate-100">Fleet Health</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Memory, disk, and monitoring agent status across your Droplets
              </p>
            </div>
            <button
              onClick={handleScanMonitoring}
              disabled={!selectedProject || monitoringLoading || loadingProjects}
              className="btn-ghost text-sm flex items-center gap-1.5 shrink-0"
            >
              {monitoringLoading ? (
                <>
                  <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                  </svg>
                  Scanning...
                </>
              ) : (
                <>
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
                  </svg>
                  Scan Fleet Health
                </>
              )}
            </button>
          </div>

          {monitoringError && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 mb-4">
              <p className="text-red-400 text-sm">{monitoringError}</p>
            </div>
          )}

          {monitoringData ? (
            <div className="space-y-4">
              {/* Summary cards: Total | No Agent | High Disk | High Memory */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="bg-slate-800/60 rounded-lg p-3 text-center">
                  <p className="text-lg font-bold text-slate-100">{monitoringData.total_droplets}</p>
                  <p className="text-xs text-slate-400 mt-0.5">Total Droplets</p>
                </div>
                <div className={`rounded-lg p-3 text-center border ${
                  monitoringData.monitoring_missing > 0
                    ? 'bg-red-500/10 border-red-500/20'
                    : 'bg-slate-800/60 border-slate-700/50'
                }`}>
                  <p className={`text-lg font-bold ${
                    monitoringData.monitoring_missing > 0 ? 'text-red-400' : 'text-slate-400'
                  }`}>
                    {monitoringData.monitoring_missing}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">No Agent</p>
                </div>
                <div className={`rounded-lg p-3 text-center border ${
                  monitoringData.high_disk > 0
                    ? 'bg-red-500/10 border-red-500/20'
                    : 'bg-slate-800/60 border-slate-700/50'
                }`}>
                  <p className={`text-lg font-bold ${
                    monitoringData.high_disk > 0 ? 'text-red-400' : 'text-slate-400'
                  }`}>
                    {monitoringData.high_disk}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">High Disk &gt;85%</p>
                </div>
                <div className={`rounded-lg p-3 text-center border ${
                  monitoringData.high_memory > 0
                    ? 'bg-amber-500/10 border-amber-500/20'
                    : 'bg-slate-800/60 border-slate-700/50'
                }`}>
                  <p className={`text-lg font-bold ${
                    monitoringData.high_memory > 0 ? 'text-amber-400' : 'text-slate-400'
                  }`}>
                    {monitoringData.high_memory}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">High Mem &gt;85%</p>
                </div>
              </div>

              {/* Droplet table */}
              {monitoringData.total_droplets === 0 ? (
                <p className="text-sm text-slate-500 text-center py-2">No Droplets found in this project.</p>
              ) : (
                <div className="border border-slate-700/50 rounded-lg overflow-hidden">
                  <div className="max-h-72 overflow-y-auto">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 bg-slate-800/90 backdrop-blur-sm">
                        <tr className="border-b border-slate-700/70">
                          <th className="text-left px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                            Droplet
                          </th>
                          <th className="text-left px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider hidden sm:table-cell">
                            Env
                          </th>
                          <th className="text-left px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                            Agent
                          </th>
                          <th className="text-right px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider hidden md:table-cell">
                            Memory
                          </th>
                          <th className="text-right px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                            Disk
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-700/40">
                        {sortedFleetDroplets(monitoringData.droplets).map((d) => (
                          <tr key={d.droplet_id} className="hover:bg-slate-700/20 transition-colors">
                            <td className="px-3 py-2 text-slate-300 font-mono text-xs max-w-[160px] truncate" title={d.droplet_name}>
                              {d.droplet_name}
                            </td>
                            <td className="px-3 py-2 hidden sm:table-cell">
                              <EnvBadge env={d.environment ?? 'unknown'} />
                            </td>
                            <td className="px-3 py-2">
                              <AgentBadge status={d.monitoring_status} />
                            </td>
                            <td className="px-3 py-2 text-right hidden md:table-cell">
                              <MetricCell value={d.memory_percent} warnAt={75} critAt={90} />
                            </td>
                            <td className="px-3 py-2 text-right">
                              <MetricCell value={d.disk_percent} warnAt={70} critAt={85} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Footer summary */}
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                <span>{monitoringData.total_droplets} droplets</span>
                {monitoringData.high_disk > 0 && (
                  <span className="text-red-400">{monitoringData.high_disk} high disk</span>
                )}
                {monitoringData.high_memory > 0 && (
                  <span className="text-amber-400">{monitoringData.high_memory} high memory</span>
                )}
                {monitoringData.monitoring_missing > 0 && (
                  <span className="text-red-400">{monitoringData.monitoring_missing} missing agent</span>
                )}
                {monitoringData.monitoring_unknown > 0 && (
                  <span>{monitoringData.monitoring_unknown} status unknown</span>
                )}
              </div>
            </div>
          ) : !monitoringLoading && (
            <p className="text-sm text-slate-500 text-center py-3">
              {selectedProject
                ? 'Click "Scan Fleet Health" to check memory, disk, and agent status.'
                : 'Select a project to scan fleet health.'}
            </p>
          )}
        </div>

      </main>
    </div>
  )
}
