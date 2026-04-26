import { requireAuth, hashPassword, verifyPassword, createToken, setSession, clearSession, getUserFromToken } from '../auth.js'
import { prisma } from '../db.js'

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

  const user = await prisma.user.findUnique({ where: { username } })
  if (!user) {
    return Response.json({ error: 'invalid credentials' }, { status: 401 })
  }

  const valid = await verifyPassword(password, user.passwordHash)
  if (!valid) {
    return Response.json({ error: 'invalid credentials' }, { status: 401 })
  }

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
