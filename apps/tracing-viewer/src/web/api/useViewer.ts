import { useCallback, useEffect, useRef, useState } from 'react'
import type { TraceData } from '@pico/contracts/tracing'
import { ViewerClient } from './client'

export function useViewer(client: ViewerClient, stopped: boolean) {
  const [data, setData] = useState<TraceData | null>(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [auto, setAuto] = useState(true)
  const [checkedAt, setCheckedAt] = useState<string | null>(null)
  const failures = useRef(0)
  const request = useRef<AbortController | null>(null)

  const refresh = useCallback(
    async (manual = false) => {
      if (stopped || request.current) return
      const controller = new AbortController()
      request.current = controller
      setLoading(true)
      if (manual) {
        client.clearArtifacts()
        setStatus('loading')
      }
      try {
        const next = await client.data(controller.signal)
        if (controller.signal.aborted) return
        if (next) setData(next)
        failures.current = 0
        setStatus('connected')
        setError('')
        setCheckedAt(new Date().toISOString())
      } catch (cause) {
        if (controller.signal.aborted) return
        setStatus('disconnected')
        setError(cause instanceof Error ? cause.message : String(cause))
        if (++failures.current >= 3) setAuto(false)
      } finally {
        if (request.current === controller) {
          request.current = null
          setLoading(false)
        }
      }
    },
    [client, stopped]
  )

  useEffect(() => {
    if (stopped) return
    void refresh()
    return () => {
      request.current?.abort()
      request.current = null
    }
  }, [refresh, stopped])

  useEffect(() => {
    if (!auto || stopped) return
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh()
    }, 15000)
    return () => window.clearInterval(timer)
  }, [auto, stopped, refresh])

  return { data, status, error, loading, auto, setAuto, checkedAt, refresh }
}
