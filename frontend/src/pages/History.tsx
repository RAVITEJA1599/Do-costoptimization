import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import api from '../services/api'
import type { HistoryItem } from '../types/analysis'

type SortKey = 'created_at' | 'resources_scanned' | 'issues_found' | 'estimated_monthly_savings'
type SortDir = 'asc' | 'desc'

const PAGE_SIZE = 10

function StatusBadge({ status }: { status: HistoryItem['status'] }) {
  const map = {
    completed: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
    running: 'bg-blue-500/10 border-blue-500/20 text-blue-400',
    pending: 'bg-slate-700/50 border-slate-600 text-slate-400',
    failed: 'bg-red-500/10 border-red-500/20 text-red-400',
  }
  return (
    <span className={`inline-flex items-center border rounded-full px-2 py-0.5 text-xs font-medium ${map[status]}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  )
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return (
    <svg className="w-3.5 h-3.5 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4M17 8v12m0 0l4-4m-4 4l-4-4" />
    </svg>
  )
  return dir === 'asc' ? (
    <svg className="w-3.5 h-3.5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
    </svg>
  ) : (
    <svg className="w-3.5 h-3.5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
    </svg>
  )
}

export default function History() {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('created_at')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [page, setPage] = useState(1)
  const navigate = useNavigate()

  useEffect(() => {
    api.get<{ analyses: HistoryItem[]; count: number }>('/history')
      .then(({ data }) => setItems(data.analyses))
      .catch(() => setError('Failed to load history.'))
      .finally(() => setLoading(false))
  }, [])

  // Reset to page 1 when search or sort changes
  useEffect(() => { setPage(1) }, [search, sortKey, sortDir])

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const MODE_LABELS: Record<string, string> = {
    fast: '⚡ Fast',
    balanced: '🧠 Balanced',
    deep: '🔍 Deep',
  }

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return items.filter(
      (item) =>
        item.project_name.toLowerCase().includes(q) ||
        item.project_id.toLowerCase().includes(q) ||
        (item.run_by ?? '').toLowerCase().includes(q) ||
        (item.analysis_mode ?? '').toLowerCase().includes(q),
    )
  }, [items, search])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let av: string | number, bv: string | number
      if (sortKey === 'estimated_monthly_savings') {
        av = parseFloat(a.estimated_monthly_savings.replace(/[^0-9.]/g, '')) || 0
        bv = parseFloat(b.estimated_monthly_savings.replace(/[^0-9.]/g, '')) || 0
      } else {
        av = a[sortKey]
        bv = b[sortKey]
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [filtered, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const paginated = sorted.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const formatDate = (ts: string) =>
    new Date(ts).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

  const ThButton = ({ label, col }: { label: string; col: SortKey }) => (
    <button
      onClick={() => toggleSort(col)}
      className="flex items-center gap-1 text-xs font-semibold text-slate-400 uppercase tracking-wider hover:text-slate-200 transition-colors"
    >
      {label}
      <SortIcon active={sortKey === col} dir={sortDir} />
    </button>
  )

  return (
    <div className="min-h-screen bg-slate-950">
      <Navbar />

      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Analysis History</h1>
            <p className="text-sm text-slate-400 mt-1">
              {items.length} past {items.length === 1 ? 'analysis' : 'analyses'}
            </p>
          </div>
          <Link to="/dashboard" className="btn-primary flex items-center gap-1.5 text-sm">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            New Analysis
          </Link>
        </div>

        {/* Search */}
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500"
            fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="search"
            placeholder="Search by project name..."
            className="input-field pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex justify-center py-16">
            <svg className="animate-spin w-8 h-8 text-blue-500" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
            </svg>
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="card p-8 text-center">
            <p className="text-slate-300 font-medium">{error}</p>
            <button onClick={() => window.location.reload()} className="btn-ghost mt-4 text-sm">
              Retry
            </button>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && sorted.length === 0 && (
          <div className="card p-16 text-center">
            {items.length === 0 ? (
              <>
                <div className="text-4xl mb-3">📊</div>
                <p className="font-semibold text-slate-200">No analyses yet</p>
                <p className="text-sm text-slate-400 mt-1">
                  Run your first analysis from the Dashboard.
                </p>
                <Link to="/dashboard" className="btn-primary inline-block mt-5 text-sm">
                  Go to Dashboard
                </Link>
              </>
            ) : (
              <>
                <p className="text-slate-300 font-medium">No results for "{search}"</p>
                <button onClick={() => setSearch('')} className="btn-ghost mt-3 text-sm">
                  Clear search
                </button>
              </>
            )}
          </div>
        )}

        {/* Table */}
        {!loading && !error && sorted.length > 0 && (
          <>
            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-700/70">
                      <th className="text-left px-4 py-3">
                        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                          Project
                        </span>
                      </th>
                      <th className="text-left px-4 py-3 hidden sm:table-cell">
                        <ThButton label="Date" col="created_at" />
                      </th>
                      <th className="text-left px-4 py-3 hidden lg:table-cell">
                        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                          Run By
                        </span>
                      </th>
                      <th className="text-left px-4 py-3 hidden lg:table-cell">
                        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                          Mode
                        </span>
                      </th>
                      <th className="text-left px-4 py-3">
                        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                          Status
                        </span>
                      </th>
                      <th className="text-right px-4 py-3 hidden md:table-cell">
                        <ThButton label="Resources" col="resources_scanned" />
                      </th>
                      <th className="text-right px-4 py-3 hidden md:table-cell">
                        <ThButton label="Issues" col="issues_found" />
                      </th>
                      <th className="text-right px-4 py-3">
                        <ThButton label="Monthly Savings" col="estimated_monthly_savings" />
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/40">
                    {paginated.map((item) => (
                      <tr
                        key={item.id}
                        onClick={() => item.status === 'completed' && navigate(`/report/${item.id}`)}
                        className={`group transition-colors ${
                          item.status === 'completed'
                            ? 'cursor-pointer hover:bg-slate-700/30'
                            : 'cursor-default'
                        }`}
                      >
                        <td className="px-4 py-3">
                          <div className={`font-medium transition-colors ${
                            item.status === 'completed'
                              ? 'text-slate-100 group-hover:text-blue-400'
                              : item.status === 'failed'
                              ? 'text-slate-400'
                              : 'text-slate-100'
                          }`}>
                            {item.project_name}
                          </div>
                          {item.status === 'failed' && item.failure_reason && (
                            <div
                              className="text-xs text-red-400 mt-0.5 truncate max-w-xs"
                              title={item.failure_reason}
                            >
                              {item.failure_reason}
                            </div>
                          )}
                          <div className="text-xs text-slate-500 sm:hidden mt-0.5">
                            {formatDate(item.created_at)}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-slate-400 hidden sm:table-cell whitespace-nowrap">
                          {formatDate(item.created_at)}
                        </td>
                        <td className="px-4 py-3 hidden lg:table-cell">
                          <span className="text-xs text-slate-400 bg-slate-800 rounded-full px-2 py-0.5">
                            {item.run_by || '—'}
                          </span>
                        </td>
                        <td className="px-4 py-3 hidden lg:table-cell">
                          <span className="text-xs text-slate-400">
                            {MODE_LABELS[item.analysis_mode ?? ''] ?? '—'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={item.status} />
                        </td>
                        <td className="px-4 py-3 text-right text-slate-300 hidden md:table-cell">
                          {item.resources_scanned}
                        </td>
                        <td className="px-4 py-3 text-right hidden md:table-cell">
                          {item.issues_found > 0 ? (
                            <span className="text-amber-400 font-medium">{item.issues_found}</span>
                          ) : (
                            <span className="text-slate-500">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {item.estimated_monthly_savings && item.estimated_monthly_savings !== '$0' ? (
                            <span className="text-emerald-400 font-medium">
                              {item.estimated_monthly_savings}
                            </span>
                          ) : (
                            <span className="text-slate-500">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between">
                <p className="text-xs text-slate-500">
                  Showing{' '}
                  <span className="text-slate-300 font-medium">
                    {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, sorted.length)}
                  </span>{' '}
                  of <span className="text-slate-300 font-medium">{sorted.length}</span> results
                </p>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="btn-ghost text-sm px-2.5 py-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    ← Prev
                  </button>
                  {Array.from({ length: totalPages }, (_, i) => i + 1)
                    .filter((n) => Math.abs(n - page) <= 2 || n === 1 || n === totalPages)
                    .reduce<(number | '…')[]>((acc, n, idx, arr) => {
                      if (idx > 0 && (arr[idx - 1] as number) < n - 1) acc.push('…')
                      acc.push(n)
                      return acc
                    }, [])
                    .map((item, idx) =>
                      item === '…' ? (
                        <span key={`ellipsis-${idx}`} className="px-1.5 text-slate-500 text-sm">…</span>
                      ) : (
                        <button
                          key={item}
                          onClick={() => setPage(item as number)}
                          className={`text-sm w-8 h-8 rounded-lg transition-colors ${
                            page === item
                              ? 'bg-blue-500 text-slate-950 font-bold'
                              : 'btn-ghost'
                          }`}
                        >
                          {item}
                        </button>
                      ),
                    )}
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="btn-ghost text-sm px-2.5 py-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Next →
                  </button>
                </div>
              </div>
            )}
          </>
        )}

      </main>
    </div>
  )
}
