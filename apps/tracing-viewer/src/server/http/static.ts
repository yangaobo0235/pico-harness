import fs from 'node:fs'
import path from 'node:path'
import type { ServerResponse } from 'node:http'
import { STATIC_DIR } from '../config/viewer.js'
import { sendText } from './responses.js'
export function serveStatic(reqPath: string, res: ServerResponse) {
  if (reqPath === '/' || reqPath === '/index.html') {
    sendText(res, 200, fs.readFileSync(path.join(STATIC_DIR, 'index.html'), 'utf8'), 'text/html; charset=utf-8')
    return
  }
  const filePath = path.resolve(path.join(STATIC_DIR, reqPath))
  if (!filePath.startsWith(path.resolve(STATIC_DIR) + path.sep)) {
    sendText(res, 403, 'Forbidden')
    return
  }
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    sendText(res, 404, 'Not found')
    return
  }
  const ext = path.extname(filePath).toLowerCase()
  const typeByExt: Record<string, string> = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8'
  }
  sendText(res, 200, fs.readFileSync(filePath, 'utf8'), typeByExt[ext] || 'text/plain; charset=utf-8')
}
