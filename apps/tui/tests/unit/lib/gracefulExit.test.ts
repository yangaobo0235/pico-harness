import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
  vi.resetModules()
})

describe('graceful process shutdown', () => {
  it.each([
    ['win32', 'SIGBREAK', 130],
    ['linux', 'SIGINT', 130],
    ['linux', 'SIGTERM', 143],
    ['linux', 'SIGHUP', 129]
  ] as const)('drains cleanup once for %s %s', async (platform, signal, code) => {
    vi.useFakeTimers()
    vi.spyOn(process, 'platform', 'get').mockReturnValue(platform)
    const handlers = new Map<string | symbol, (...args: unknown[]) => void>()

    vi.spyOn(process, 'on').mockImplementation((event, listener) => {
      handlers.set(event, listener)

      return process
    })
    const exit = vi.spyOn(process, 'exit').mockImplementation(() => undefined as never)
    const cleanup = vi.fn(async () => {})
    const onSignal = vi.fn()
    const { setupGracefulExit } = await import('../../../src/platform/gracefulExit.js')

    setupGracefulExit({ cleanups: [cleanup], onSignal })
    expect(handlers.has('SIGBREAK')).toBe(platform === 'win32')
    handlers.get(signal)!()
    handlers.get('SIGTERM')!()

    await vi.waitFor(() => expect(exit).toHaveBeenCalledWith(code))
    expect(cleanup).toHaveBeenCalledTimes(1)
    expect(onSignal).toHaveBeenCalledExactlyOnceWith(signal)
    vi.clearAllTimers()
  })
})
