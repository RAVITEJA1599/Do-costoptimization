import { useState } from 'react'
import type { AnalysisFinding } from '../types/analysis'

interface Props {
  findings: AnalysisFinding[]
}

function SeverityBadge({ severity }: { severity: string }) {
  if (severity === 'high') return <span className="badge-high">High</span>
  if (severity === 'medium') return <span className="badge-medium">Medium</span>
  return <span className="badge-low">Low</span>
}

function ResourceIcon({ type }: { type: string }) {
  const icons: Record<string, string> = {
    droplet: '💧',
    volume: '💾',
    snapshot: '📸',
    database: '🗄️',
    load_balancer: '⚖️',
    floating_ip: '🌐',
  }
  return <span className="text-base">{icons[type] ?? '📦'}</span>
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }).catch(() => {})
  }

  return (
    <button
      onClick={(e) => { e.stopPropagation(); handleCopy() }}
      className="shrink-0 p-1 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-700
                 transition-colors duration-150"
      title={copied ? 'Copied!' : 'Copy to clipboard'}
    >
      {copied ? (
        <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      )}
    </button>
  )
}

function RemediationStep({ step, index }: { step: string; index: number }) {
  // Detect doctl commands anywhere in the step
  const cmdMatch = step.match(/\bdoctl\b.+/)
  const cmd = cmdMatch ? cmdMatch[0].trim() : null
  const prefix = cmd ? step.slice(0, step.indexOf(cmd)).replace(/[:]\s*$/, '').trim() : null

  return (
    <li className="flex gap-2 text-sm">
      <span className="shrink-0 w-5 h-5 rounded-full bg-slate-700 flex items-center justify-center text-xs text-slate-400 font-medium mt-0.5">
        {index + 1}
      </span>
      <div className="flex-1 min-w-0 space-y-1">
        {prefix && <span className="text-slate-300">{prefix}</span>}
        {cmd ? (
          <div className="flex items-center gap-1 bg-slate-900/70 border border-slate-700 rounded-md px-2.5 py-1.5">
            <code className="text-blue-300 font-mono text-xs flex-1 break-all">{cmd}</code>
            <CopyButton text={cmd} />
          </div>
        ) : (
          !prefix && <span className="text-slate-300">{step}</span>
        )}
      </div>
    </li>
  )
}

export default function FindingsTable({ findings }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null)

  if (findings.length === 0) {
    return (
      <div className="card p-12 text-center">
        <div className="text-4xl mb-3">✅</div>
        <p className="font-semibold text-slate-200">No Issues Found</p>
        <p className="text-sm text-slate-400 mt-1">Your infrastructure looks well-optimized.</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {findings.map((f, i) => {
        const isOpen = expanded === i
        return (
          <div key={i} className="card overflow-hidden">
            {/* Header row */}
            <button
              onClick={() => setExpanded(isOpen ? null : i)}
              className="w-full flex items-center gap-4 p-4 text-left hover:bg-slate-700/30 transition-colors"
            >
              <ResourceIcon type={f.resource_type} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-slate-100 text-sm">{f.resource_name}</span>
                  <span className="text-xs text-slate-500 bg-slate-700 px-1.5 py-0.5 rounded">
                    {f.resource_type}
                  </span>
                  <SeverityBadge severity={f.severity} />
                </div>
                <p className="text-xs text-slate-400 mt-0.5 truncate">{f.issue}</p>
              </div>
              <div className="text-right shrink-0">
                <p className="text-emerald-400 font-semibold text-sm">{f.monthly_savings}</p>
                <p className="text-xs text-slate-500">per month</p>
              </div>
              <svg
                className={`w-4 h-4 text-slate-500 shrink-0 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {/* Expanded detail */}
            {isOpen && (
              <div className="px-4 pb-4 border-t border-slate-700/50 pt-4 space-y-4">
                <div>
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Issue</p>
                  <p className="text-sm text-slate-300">{f.issue}</p>
                </div>

                <div>
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Recommendation</p>
                  <p className="text-sm text-slate-300">{f.recommendation}</p>
                </div>

                <div>
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                    Remediation Steps
                  </p>
                  <ol className="space-y-2">
                    {f.remediation_steps.map((step, j) => (
                      <RemediationStep key={j} step={step} index={j} />
                    ))}
                  </ol>
                </div>

                <div className="flex gap-4 pt-1">
                  <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
                    <p className="text-xs text-slate-400">Monthly</p>
                    <p className="text-emerald-400 font-bold">{f.monthly_savings}</p>
                  </div>
                  <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-2">
                    <p className="text-xs text-slate-400">Annual</p>
                    <p className="text-blue-400 font-bold">{f.annual_savings}</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
