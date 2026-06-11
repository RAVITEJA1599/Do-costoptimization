export default function TokenUsage({
  inputTokens,
  outputTokens,
}: {
  inputTokens: number
  outputTokens: number
}) {
  const totalTokens = inputTokens + outputTokens

  return (
    <div className="card p-4 bg-gradient-to-r from-purple-500/5 to-blue-500/5 border-purple-500/20">
      <div className="flex items-start gap-4">
        <div className="w-10 h-10 rounded-xl bg-purple-500/20 border border-purple-500/30 flex items-center justify-center shrink-0">
          <svg className="w-5 h-5 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-slate-100 mb-2">Token Usage</h3>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <p className="text-xs text-slate-400">Input</p>
              <p className="text-lg font-bold text-slate-100">{inputTokens.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-slate-400">Output</p>
              <p className="text-lg font-bold text-slate-100">{outputTokens.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-slate-400">Total</p>
              <p className="text-lg font-bold text-purple-400">{totalTokens.toLocaleString()}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
