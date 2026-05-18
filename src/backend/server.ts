import { resolve, join, extname } from 'path'
import { existsSync, statSync, readdirSync, readFileSync } from 'fs'
import { handleAuth } from './routes/auth.js'
import { handleJournal } from './routes/journal.js'
import { handleCheckins } from './routes/checkins.js'
import { handleBaseline } from './routes/baseline.js'
import { handleChat } from './routes/chat.js'
import { handleNote } from './routes/note.js'
import { handleKiwix } from './routes/kiwix.js'
import { handleSources } from './routes/sources.js'
import { setCheckinService, LlamaCheckinService, DeterministicCheckinService } from './checkinService.js'
import { setChatService, LlamaChatService, DeterministicChatService } from './chatService.js'
import { prisma } from './db.js'

const PORT = Number(process.env.ELFIN_PORT ?? 8885)
const STATIC_DIR = resolve(process.env.STATIC_DIR ?? './static')
const KIWIX_URL = process.env.KIWIX_URL || 'http://localhost:8083'
const KIWIX_PUBLIC_URL = process.env.KIWIX_PUBLIC_URL || ''

const INFERENCE_ENDPOINT = process.env.ELFIN_INFERENCE_ENDPOINT
if (INFERENCE_ENDPOINT) {
  setCheckinService(new LlamaCheckinService(INFERENCE_ENDPOINT, new DeterministicCheckinService()))
  console.log(`elfin AI check-in enabled: ${INFERENCE_ENDPOINT}`)
  setChatService(new LlamaChatService(INFERENCE_ENDPOINT, new DeterministicChatService()))
  console.log(`elfin AI chat enabled: ${INFERENCE_ENDPOINT}`)
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

async function proxyToKiwix(targetUrl: string, req: Request): Promise<Response> {
  try {
    let url = targetUrl
    for (let i = 0; i < 5; i++) {
      const proxyRes = await fetch(url, {
        method: req.method,
        headers: req.headers,
        body: req.method !== 'GET' && req.method !== 'HEAD' ? req.body : undefined,
        redirect: 'manual',
        signal: AbortSignal.timeout(30_000),
      })
      if (proxyRes.status >= 300 && proxyRes.status < 400) {
        const location = proxyRes.headers.get('location')
        if (location) {
          url = location.startsWith('/') ? `${KIWIX_URL}${location}` : location
          continue
        }
      }
      const headers = new Headers(proxyRes.headers)
      headers.delete('content-security-policy')
      headers.delete('x-frame-options')
      headers.delete('content-encoding')
      headers.delete('content-length')
      return new Response(proxyRes.body, { status: proxyRes.status, headers })
    }
    return new Response('Too many redirects', { status: 502 })
  } catch {
    return new Response('Kiwix unavailable', { status: 502 })
  }
}

const server = Bun.serve({
  port: PORT,
  idleTimeout: 255,
  maxRequestBodySize: 5 * 1024 * 1024,
  async fetch(req) {
    const url = new URL(req.url)
    const path = url.pathname

    if (path === '/kiwix' || path.startsWith('/kiwix/')) {
      const kiwixPath = path.replace(/^\/kiwix\/?/, '/') || '/'
      return proxyToKiwix(`${KIWIX_URL}${kiwixPath}${url.search}`, req)
    }

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

      const chatRes = await handleChat(req, path)
      if (chatRes) return chatRes

      const noteRes = await handleNote(req, path)
      if (noteRes) return noteRes

      const kiwixRes = await handleKiwix(req, path)
      if (kiwixRes) return kiwixRes

      const sourcesRes = await handleSources(req, path)
      if (sourcesRes) return sourcesRes

      if (path === '/api/health' && req.method === 'GET') {
        return Response.json({ status: 'healthy', version: '0.1.0' })
      }

      if (path === '/api/config' && req.method === 'GET') {
        return Response.json({
          kiwixPublicUrl: KIWIX_PUBLIC_URL || null,
        })
      }

      if (path === '/api/status' && req.method === 'GET') {
        const llmUrl = process.env.ELFIN_INFERENCE_ENDPOINT || 'http://localhost:8081'
        const embedUrl = process.env.ELFIN_EMBED_ENDPOINT || 'http://localhost:8082'
        const qdrantUrl = process.env.QDRANT_URL || 'http://localhost:6333'
        const qdrantCollection = process.env.QDRANT_COLLECTION || 'elfin_docs'

        const result = { llm: 'err', embed: 'err', qdrant: 'err', kiwix: 'err', documents: 0 }

        await Promise.allSettled([
          fetch(`${llmUrl}/health`, { signal: AbortSignal.timeout(3000) })
            .then(r => { if (r.ok) result.llm = 'ok' }),
          fetch(`${embedUrl}/health`, { signal: AbortSignal.timeout(3000) })
            .then(r => { if (r.ok) result.embed = 'ok' }),
          fetch(`${qdrantUrl}/collections/${qdrantCollection}`, { signal: AbortSignal.timeout(3000) })
            .then(async r => {
              if (r.ok) {
                result.qdrant = 'ok'
                const d = await r.json()
                result.documents = d.result?.points_count || 0
              }
            }),
          fetch(`${KIWIX_URL}/catalog/v2/root.xml`, { signal: AbortSignal.timeout(3000) })
            .then(r => { if (r.ok) result.kiwix = 'ok' }),
        ])

        return Response.json(result)
      }

      if (path === '/api/thermals' && req.method === 'GET') {
        try {
          const base = '/sys/class/thermal'
          const zones = readdirSync(base).filter(d => d.startsWith('thermal_zone'))
          const temps = zones.map(z => {
            const type = readFileSync(join(base, z, 'type'), 'utf-8').trim()
            const temp = parseInt(readFileSync(join(base, z, 'temp'), 'utf-8').trim(), 10)
            return { zone: type, temp: Math.round(temp / 100) / 10 }
          })
          return Response.json({ temps, ts: Date.now() })
        } catch {
          return Response.json({ temps: [], ts: Date.now() })
        }
      }

      return Response.json({ error: 'not found' }, { status: 404 })
    }

    // Static files
    const staticResponse = serveStatic(path)
    if (staticResponse) return staticResponse

    // SPA fallback — only for known Elfin frontend routes
    const SPA_ROUTES = ['/', '/chat', '/notes', '/encyclopedia', '/system', '/login']
    const indexPath = join(STATIC_DIR, 'index.html')
    if (SPA_ROUTES.includes(path) && existsSync(indexPath)) {
      const frameSrc = KIWIX_PUBLIC_URL ? `'self' ${KIWIX_PUBLIC_URL}` : `'self'`
      return new Response(Bun.file(indexPath), {
        headers: {
          'Content-Type': 'text/html',
          'Content-Security-Policy': `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'self'; frame-src ${frameSrc}`,
          'X-Content-Type-Options': 'nosniff',
        },
      })
    }

    // Everything else proxies to Kiwix (article paths, /_mw_/, etc.)
    return proxyToKiwix(`${KIWIX_URL}${path}${url.search}`, req)
  },
})

console.log(`elfin listening on http://localhost:${server.port}`)

// Background worker to clean up demo users after 24 hours
if (process.env.DEMO_MODE === 'true') {
  console.log('Demo mode enabled. Starting cleanup worker.')
  setInterval(async () => {
    try {
      const twentyFourHoursAgo = new Date(Date.now() - 24 * 60 * 60 * 1000)
      const result = await prisma.user.deleteMany({
        where: {
          username: { startsWith: 'demo_' },
          createdAt: { lt: twentyFourHoursAgo },
        },
      })
      if (result.count > 0) {
        console.log(`Cleaned up ${result.count} expired demo user(s).`)
      }
    } catch (err) {
      console.error('Failed to run demo user cleanup:', err)
    }
  }, 60 * 60 * 1000) // Run every hour
}
