import type { IncomingMessage, ServerResponse } from 'node:http'
import { PORT, SHUTDOWN_HEADER } from '../config/viewer.js'
export function isTrustedShutdownRequest(req: IncomingMessage) {
  const origin = req.headers.origin
  return (
    req.method === 'POST' &&
    req.headers[SHUTDOWN_HEADER] === 'shutdown' &&
    (!origin || origin === `http://127.0.0.1:${PORT}`)
  )
}

export function sendJson(res: ServerResponse, statusCode: number, payload: unknown) {
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store'
  })
  res.end(JSON.stringify(payload))
}

export function sendJsonText(
  res: ServerResponse,
  statusCode: number,
  text: string,
  headers: Record<string, string> = {}
) {
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-cache',
    ...headers
  })
  res.end(text)
}

export function sendText(
  res: ServerResponse,
  statusCode: number,
  text: string,
  contentType: string = 'text/plain; charset=utf-8'
) {
  res.writeHead(statusCode, {
    'Content-Type': contentType,
    'Cache-Control': 'no-store'
  })
  res.end(text)
}
