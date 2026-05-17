import { resolve, join, extname, basename } from 'path'
import { existsSync, statSync } from 'fs'
import { requireAuth } from '../auth.js'

const SOURCE_DIR = resolve(process.env.ELFIN_SOURCE_DIR ?? './data/datasets/raw')

const MIME_TYPES: Record<string, string> = {
  '.pdf': 'application/pdf',
  '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.htm': 'text/html; charset=utf-8',
  '.epub': 'application/epub+zip',
}

export async function handleSources(req: Request, path: string): Promise<Response | null> {
  const pathname = path.split('?')[0]!
  const parts = pathname.split('/').filter(Boolean)
  if (parts[1] !== 'sources') return null

  try {
    const url = new URL(req.url)
    const tokenParam = url.searchParams.get('token')
    const proxyReq = tokenParam
      ? new Request(req.url, { method: req.method, headers: { ...Object.fromEntries(req.headers), authorization: `Bearer ${tokenParam}` } })
      : req
    await requireAuth(proxyReq)

    if (parts.length !== 3 || req.method !== 'GET') {
      return Response.json({ error: 'not found' }, { status: 404 })
    }

    const requested = decodeURIComponent(parts[2]!)
    const safe = basename(requested)
    if (!safe || safe !== requested || safe.startsWith('.')) {
      return Response.json({ error: 'invalid filename' }, { status: 400 })
    }

    const filePath = join(SOURCE_DIR, safe)
    if (!filePath.startsWith(SOURCE_DIR + '/') && filePath !== SOURCE_DIR) {
      return Response.json({ error: 'invalid path' }, { status: 400 })
    }
    if (!existsSync(filePath) || !statSync(filePath).isFile()) {
      return Response.json({ error: 'source not found' }, { status: 404 })
    }

    const ext = extname(filePath).toLowerCase()
    const contentType = MIME_TYPES[ext] ?? 'application/octet-stream'
    const file = Bun.file(filePath)

    return new Response(file, {
      headers: {
        'Content-Type': contentType,
        'Content-Disposition': `inline; filename="${safe}"`,
        'Cache-Control': 'private, max-age=300',
      },
    })
  } catch (err: any) {
    if (err.message === 'missing token' || err.message === 'invalid token' || err.message === 'user not found') {
      return Response.json({ error: err.message }, { status: 401 })
    }
    console.error('Sources API Error:', err)
    return Response.json({ error: 'internal server error' }, { status: 500 })
  }
}
