import http from 'node:http'
import { PORT, STATE_DIR } from '../config/viewer.js'
import { isTrustedShutdownRequest, sendJson, sendJsonText } from './responses.js'
import { serveStatic } from './static.js'
import { dataSnapshot } from '../tracing/snapshot.js'
import { readArtifact } from '../tracing/artifacts.js'
import { searchSpans } from '../tracing/search.js'
import { loadDescriptors } from '../tracing/descriptors.js'
const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || '127.0.0.1'}`)

  if (url.pathname === '/api/health') {
    sendJson(res, 200, { ok: true, port: PORT, stateDir: STATE_DIR })
    return
  }

  if (url.pathname === '/api/shutdown') {
    if (!isTrustedShutdownRequest(req)) {
      sendJson(res, 403, { error: 'Forbidden' })
      return
    }
    sendJson(res, 200, { ok: true, stopping: true })
    res.once('finish', () => {
      server.close(() => process.exit(0))
      setTimeout(() => process.exit(0), 1000).unref()
    })
    return
  }

  if (url.pathname === '/api/descriptors') {
    sendJson(res, 200, { descriptors: loadDescriptors() })
    return
  }

  if (url.pathname === '/api/search') {
    sendJson(res, 200, { results: searchSpans(url.searchParams.get('q') || '') })
    return
  }

  if (url.pathname === '/api/data') {
    const snapshot = dataSnapshot()
    if (req.headers['if-none-match'] === snapshot.etag) {
      res.writeHead(304, { ETag: snapshot.etag, 'Cache-Control': 'no-cache' })
      res.end()
      return
    }
    sendJsonText(res, 200, snapshot.text, { ETag: snapshot.etag })
    return
  }

  if (url.pathname === '/api/artifact') {
    const artifactPath = url.searchParams.get('path')
    const artifact = readArtifact(artifactPath)
    if (!artifact) {
      sendJson(res, 404, { error: 'Artifact not found' })
      return
    }
    sendJson(res, 200, artifact)
    return
  }

  serveStatic(url.pathname, res)
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Trace UI running at http://127.0.0.1:${PORT}`)
})
