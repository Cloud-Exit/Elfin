import { requireAuth } from '../auth.js'

const KIWIX_URL = process.env.KIWIX_URL || 'http://localhost:8083'

export async function handleKiwix(req: Request, path: string): Promise<Response | null> {
  const url = new URL(req.url)
  const pathname = url.pathname

  if (!pathname.startsWith('/api/kiwix')) return null

  try {
    // Authenticate the request. 
    // Since an iframe might not easily send headers, we could check a cookie or token in query params.
    // For now, let's use a standard token check. If this causes issues with iframes, we may need a workaround.
    const tokenParams = url.searchParams.get('token')
    
    // Clone the request to modify headers if needed
    const proxyReq = new Request(req)
    if (tokenParams) {
      proxyReq.headers.set('Authorization', `Bearer ${tokenParams}`)
    }
    
    await requireAuth(proxyReq)
    
    // Strip '/api/kiwix' and proxy the rest
    const targetPath = pathname.replace('/api/kiwix', '') || '/'
    const targetUrl = new URL(targetPath + url.search, KIWIX_URL)
    
    // Fetch from kiwix
    const proxyRes = await fetch(targetUrl, {
      method: req.method,
      headers: req.headers,
      body: req.method !== 'GET' && req.method !== 'HEAD' ? req.body : undefined
    })

    // Return the response directly
    return new Response(proxyRes.body, {
      status: proxyRes.status,
      statusText: proxyRes.statusText,
      headers: proxyRes.headers,
    })
  } catch (err: any) {
    if (err.message === 'missing token' || err.message === 'invalid token' || err.message === 'user not found') {
      return Response.json({ error: err.message }, { status: 401 })
    }
    console.error('Kiwix API Error:', err)
    return Response.json({ error: err.message }, { status: 400 })
  }
}
