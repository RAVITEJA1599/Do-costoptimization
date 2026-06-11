import { useEffect, useRef, useState } from 'react'
import type { ProgressMessage } from '../types/analysis'

interface Props {
  analysisId: string
  token?: string
  onComplete?: () => void
  onError?: (msg: string) => void
}

export default function ProgressTracker({ analysisId, token, onComplete, onError }: Props) {
  const [messages, setMessages] = useState<ProgressMessage[]>([])
  const [currentPct, setCurrentPct] = useState(0)
  const [isDone, setIsDone] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const logRef = useRef<HTMLDivElement>(null)

  // Ref-based callback dispatch.
  //
  // Assigning to .current during render (not inside an effect) is intentional:
  // the ref object is stable across renders, so onmessage always invokes the
  // latest callback version without needing to restart the WebSocket each time
  // the parent re-renders and passes a new function identity.
  const onCompleteRef = useRef(onComplete)
  const onErrorRef = useRef(onError)
  onCompleteRef.current = onComplete
  onErrorRef.current = onError

  useEffect(() => {
    // `alive` — false once this effect's cleanup has run.
    //   • Guards onmessage against writing state after unmount.
    //   • Lets onopen detect a React Strict Mode double-invoke and discard
    //     the superseded socket before it ever receives messages.
    //   • Lets onclose distinguish a deliberate cleanup-close from a
    //     genuine unexpected disconnect.
    let alive = true

    // `settled` — true once we receive a terminal status frame (completed/failed).
    // Prevents onclose from logging a spurious warning after the server
    // intentionally closes the connection at the end of an analysis.
    let settled = false

    const backendUrl = import.meta.env.VITE_API_BASE_URL || window.location.origin
    const wsBase = backendUrl
      .replace('http://', 'ws://')
      .replace('https://', 'wss://')
    const wsUrl = token
      ? `${wsBase}/ws/progress/${analysisId}?token=${encodeURIComponent(token)}`
      : `${wsBase}/ws/progress/${analysisId}`

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      // React Strict Mode fires the effect, runs cleanup (alive=false), then
      // fires the effect again.  The first socket may still be CONNECTING when
      // cleanup runs, so we rely on onopen to close it once it finally opens.
      if (!alive) {
        ws.close(1000, 'Superseded by newer connection')
      }
    }

    ws.onmessage = (e: MessageEvent) => {
      if (!alive) return

      let msg: ProgressMessage
      try {
        msg = JSON.parse(e.data) as ProgressMessage
      } catch {
        return
      }

      setMessages((prev) => [...prev, msg])
      setCurrentPct(msg.progress_pct)

      if (msg.status === 'completed') {
        settled = true
        setIsDone(true)
        ws.close(1000, 'Analysis complete')
        onCompleteRef.current?.()
      } else if (msg.status === 'failed') {
        settled = true
        setIsDone(true)
        ws.close(1000, 'Analysis failed')
        onErrorRef.current?.(msg.message)
      }
    }

    ws.onerror = () => {
      // Browsers surface no actionable detail in the error event.
      // The close event fires immediately after and is handled below.
    }

    ws.onclose = (event: CloseEvent) => {
      // Only surface unexpected closes: analysis hadn't finished, this
      // effect is still the live one, and we didn't close it ourselves.
      if (!settled && alive && event.code !== 1000) {
        console.warn(
          `[ProgressTracker] WebSocket closed unexpectedly — ` +
            `code=${event.code}, reason="${event.reason}"`,
        )
      }
    }

    return () => {
      alive = false
      // Close in both CONNECTING and OPEN states; CLOSING/CLOSED are already
      // terminal and WebSocket.close() is a no-op for them.
      if (
        ws.readyState === WebSocket.CONNECTING ||
        ws.readyState === WebSocket.OPEN
      ) {
        ws.close(1000, 'Component unmounted')
      }
    }
  // Only restart the WebSocket when the target analysis or auth token changes.
  // onComplete / onError are intentionally excluded — they are accessed via
  // refs so their identity changes never disconnect an active socket.
  }, [analysisId, token])

  // Auto-scroll log to bottom
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [messages])

  const latestMsg = messages[messages.length - 1]

  return (
    <div className="card p-6 animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-slate-100">Analysis Progress</h3>
        {!isDone && (
          <span className="flex items-center gap-1.5 text-xs text-blue-400">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
            Running
          </span>
        )}
        {isDone && (
          <span className="flex items-center gap-1.5 text-xs text-emerald-400">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Complete
          </span>
        )}
      </div>

      {/* Progress bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-slate-400 mb-1.5">
          <span>{latestMsg?.message ?? 'Initializing...'}</span>
          <span>{currentPct}%</span>
        </div>
        <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-blue-600 to-blue-400 rounded-full transition-all duration-500"
            style={{ width: `${currentPct}%` }}
          />
        </div>
      </div>

      {/* Stage log */}
      <div
        ref={logRef}
        className="bg-slate-900 rounded-lg p-3 h-48 overflow-y-auto font-mono text-xs space-y-1"
      >
        {messages.length === 0 && (
          <p className="text-slate-500">Waiting for updates...</p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="text-slate-600 shrink-0">
              {String(msg.stage).padStart(2, '0')}/{msg.total_stages}
            </span>
            {msg.status === 'completed' ? (
              <svg className="w-3 h-3 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : msg.status === 'failed' ? (
              <svg className="w-3 h-3 text-red-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <span className="w-1 h-1 rounded-full bg-blue-400 animate-pulse shrink-0 mx-1" />
            )}
            <span className={msg.status === 'failed' ? 'text-red-400' : 'text-slate-300'}>
              {msg.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
