import { requireAuth, hashPassword, verifyPassword, createToken, setSession, clearSession, getUserFromToken } from '../auth.js'
import { prisma } from '../db.js'

const loginAttempts = new Map<string, { count: number; blockedUntil: number }>()
const LOGIN_MAX_ATTEMPTS = 5
const LOGIN_BLOCK_MS = 15 * 60 * 1000

export async function handleAuth(req: Request, path: string): Promise<Response | null> {
  try {
    if (path === '/api/auth/login' && req.method === 'POST') {
      return await login(req)
    }
    if (path === '/api/auth/logout' && req.method === 'POST') {
      return await logout(req)
    }
    if (path === '/api/auth/me' && req.method === 'GET') {
      return await me(req)
    }
    if (path === '/api/auth/change-password' && req.method === 'POST') {
      return await changePassword(req)
    }
    if (path === '/api/auth/config' && req.method === 'GET') {
      return await getConfig(req)
    }
    if (path === '/api/auth/demo' && req.method === 'POST') {
      return await startDemo(req)
    }
    return null
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 401 })
  }
}

async function login(req: Request): Promise<Response> {
  const body = await req.json().catch(() => ({}))
  const { username, password } = body
  if (!username || !password) {
    return Response.json({ error: 'username and password required' }, { status: 400 })
  }

  const now = Date.now()
  const key = username.toLowerCase()
  const attempts = loginAttempts.get(key)
  if (attempts && now < attempts.blockedUntil) {
    return Response.json({ error: 'too many login attempts, try again later' }, { status: 429 })
  }

  const user = await prisma.user.findUnique({ where: { username } })
  if (!user) {
    trackFailedLogin(key, now)
    return Response.json({ error: 'invalid credentials' }, { status: 401 })
  }

  const valid = await verifyPassword(password, user.passwordHash)
  if (!valid) {
    trackFailedLogin(key, now)
    return Response.json({ error: 'invalid credentials' }, { status: 401 })
  }

  loginAttempts.delete(key)
  const token = createToken()
  setSession(token, user.id)

  return Response.json({
    token,
    user: {
      id: user.id,
      username: user.username,
      role: user.role,
      mustChangePassword: user.mustChangePassword,
    },
  })
}

function trackFailedLogin(key: string, now: number): void {
  const entry = loginAttempts.get(key)
  if (!entry || now >= entry.blockedUntil) {
    loginAttempts.set(key, { count: 1, blockedUntil: 0 })
    return
  }
  entry.count++
  if (entry.count >= LOGIN_MAX_ATTEMPTS) {
    entry.blockedUntil = now + LOGIN_BLOCK_MS
  }
}

async function logout(req: Request): Promise<Response> {
  const auth = req.headers.get('authorization') ?? ''
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : auth
  if (token) clearSession(token)
  return Response.json({ ok: true })
}

async function me(req: Request): Promise<Response> {
  const auth = req.headers.get('authorization') ?? ''
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : auth
  if (!token) {
    return Response.json({ error: 'missing token' }, { status: 401 })
  }

  const user = await getUserFromToken(token)
  if (!user) {
    return Response.json({ error: 'invalid token' }, { status: 401 })
  }

  return Response.json({ user })
}

async function changePassword(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const body = await req.json().catch(() => ({}))
  const { oldPassword, newPassword } = body

  if (!oldPassword || !newPassword || newPassword.length < 8) {
    return Response.json({ error: 'oldPassword and newPassword (min 8 chars) required' }, { status: 400 })
  }

  const user = await prisma.user.findUnique({ where: { id: ctx.userId } })
  if (!user) {
    return Response.json({ error: 'user not found' }, { status: 404 })
  }

  const valid = await verifyPassword(oldPassword, user.passwordHash)
  if (!valid) {
    return Response.json({ error: 'invalid old password' }, { status: 401 })
  }

  const newHash = await hashPassword(newPassword)
  await prisma.user.update({
    where: { id: ctx.userId },
    data: { passwordHash: newHash, mustChangePassword: false },
  })

  return Response.json({ ok: true })
}

async function getConfig(req: Request): Promise<Response> {
  return Response.json({
    demoMode: process.env.DEMO_MODE === 'true'
  })
}

const demoCreates = new Map<string, number>()
const DEMO_COOLDOWN = 5_000

async function startDemo(req: Request): Promise<Response> {
  if (process.env.DEMO_MODE !== 'true') {
    return Response.json({ error: 'Demo mode is not enabled' }, { status: 403 })
  }

  const ip = req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ?? 'unknown'
  const now = Date.now()
  const lastCreate = demoCreates.get(ip) ?? 0
  if (now - lastCreate < DEMO_COOLDOWN) {
    return Response.json({ error: 'too many demo accounts, try again shortly' }, { status: 429 })
  }
  demoCreates.set(ip, now)
  if (demoCreates.size > 500) {
    for (const [k, v] of demoCreates) { if (now - v > DEMO_COOLDOWN) demoCreates.delete(k) }
  }

  const username = `demo_${crypto.randomUUID()}`
  const password = crypto.randomUUID()
  const hash = await hashPassword(password)

  console.log(`Demo account created: ${username} from IP ${ip}`)

  const user = await prisma.user.create({
    data: {
      username,
      passwordHash: hash,
      role: 'user',
      mustChangePassword: false,
    },
  })

  const token = createToken()
  setSession(token, user.id)

  return Response.json({
    token,
    user: {
      id: user.id,
      username: user.username,
      role: user.role,
      mustChangePassword: user.mustChangePassword,
    },
  })
}
