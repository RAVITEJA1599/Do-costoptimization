interface Props {
  value: string
  onChange: (mode: string) => void
  disabled?: boolean
}

const MODES = [
  {
    id: 'fast',
    icon: '⚡',
    label: 'Fast',
    sub: 'Claude Haiku · Cheapest',
  },
  {
    id: 'balanced',
    icon: '🧠',
    label: 'Balanced',
    sub: 'Claude Sonnet · Recommended',
  },
  {
    id: 'deep',
    icon: '🔍',
    label: 'Deep',
    sub: 'Claude Opus · Most thorough',
  },
]

export default function AnalysisModeSelector({ value, onChange, disabled }: Props) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-400 mb-1.5">
        Analysis Mode
      </label>
      <div className="grid grid-cols-3 gap-2">
        {MODES.map((mode) => {
          const active = value === mode.id
          return (
            <button
              key={mode.id}
              type="button"
              disabled={disabled}
              onClick={() => onChange(mode.id)}
              className={`
                flex flex-col items-center gap-1 px-2 py-2.5 rounded-lg border text-center
                transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed
                ${active
                  ? 'bg-blue-600/20 border-blue-500/60 text-blue-300'
                  : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-300'
                }
              `}
            >
              <span className="text-lg leading-none">{mode.icon}</span>
              <span className="text-xs font-semibold">{mode.label}</span>
              <span className="text-[10px] text-slate-500 leading-tight">{mode.sub}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
