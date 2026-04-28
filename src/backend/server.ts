import { resolve, join, extname } from 'path'
import { existsSync, statSync } from 'fs'
import { handleAuth } from './routes/auth.js'
import { handleJournal } from './routes/journal.js'
import { handleCheckins } from './routes/checkins.js'
import { handleBaseline } from './routes/baseline.js'
import { setCheckinService, LlamaCheckinService, DeterministicCheckinService } from './checkinService.js'

const PORT = Number(process.env.ELFIN_PORT ?? 8085)
const STATIC_DIR = resolve(process.env.STATIC_DIR ?? './static')

const INFERENCE_ENDPOINT = process.env.ELFIN_INFERENCE_ENDPOINT
if (INFERENCE_ENDPOINT) {
  setCheckinService(new LlamaCheckinService(INFERENCE_ENDPOINT, new DeterministicCheckinService()))
  console.log(`elfin AI check-in enabled: ${INFERENCE_ENDPOINT}`)
}

const MIME_TYPES: Record<string, string> = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.wasm': 'application/wasm',
}

function serveStatic(path: string): Response | null {
  const filePath = join(STATIC_DIR, path)

  // Prevent directory traversal
  if (!filePath.startsWith(STATIC_DIR)) return null

  if (!existsSync(filePath) || !statSync(filePath).isFile()) return null

  const file = Bun.file(filePath)
  const ext = extname(filePath)
  const contentType = MIME_TYPES[ext] ?? 'application/octet-stream'

  return new Response(file, {
    headers: { 'Content-Type': contentType },
  })
}

const server = Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url)
    const path = url.pathname

    // API routes
    if (path.startsWith('/api/')) {
      const authRes = await handleAuth(req, path)
      if (authRes) return authRes

      const journalRes = await handleJournal(req, path)
      if (journalRes) return journalRes

      const checkinRes = await handleCheckins(req, path)
      if (checkinRes) return checkinRes

      const baselineRes = await handleBaseline(req, path)
      if (baselineRes) return baselineRes

      if (path === '/api/health' && req.method === 'GET') {
        return Response.json({ status: 'healthy', version: '0.1.0' })
      }

      return Response.json({ error: 'not found' }, { status: 404 })
    }

    // Static files
    const staticResponse = serveStatic(path)
    if (staticResponse) return staticResponse

    // SPA fallback — serve index.html for all non-file routes
    const indexPath = join(STATIC_DIR, 'index.html')
    if (existsSync(indexPath)) {
      return new Response(Bun.file(indexPath), {
        headers: { 'Content-Type': 'text/html' },
      })
    }

    return new Response('Not Found', { status: 404 })
  },
})

console.log(`elfin listening on http://localhost:${server.port}`)
