import { prisma } from './db.js'

export type AuthContext = { userId: string; role: string }

const SESSION_TTL = 24 * 60 * 60 * 1000

export async function hashPassword(password: string): Promise<string> {
  return Bun.password.hash(password, { algorithm: 'bcrypt', cost: 12 })
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  return Bun.password.verify(password, hash)
}

export function createToken(): string {
  return crypto.randomUUID()
}

export async function setSession(token: string, userId: string): Promise<void> {
  await prisma.session.create({
    data: { id: token, userId, expiresAt: new Date(Date.now() + SESSION_TTL) },
  })
}

export async function clearSession(token: string): Promise<void> {
  await prisma.session.delete({ where: { id: token } }).catch(() => {})
}

async function getValidSession(token: string): Promise<string | null> {
  const entry = await prisma.session.findUnique({ where: { id: token } })
  if (!entry) return null
  if (new Date() > entry.expiresAt) {
    await prisma.session.delete({ where: { id: token } }).catch(() => {})
    return null
  }
  return entry.userId
}

export async function requireAuth(req: Request): Promise<AuthContext> {
  const auth = req.headers.get('authorization') ?? ''
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : auth
  if (!token) throw new Error('missing token')

  const userId = await getValidSession(token)
  if (!userId) throw new Error('invalid token')

  const user = await prisma.user.findUnique({ where: { id: userId } })
  if (!user) throw new Error('user not found')

  return { userId: user.id, role: user.role }
}

export async function getUserFromToken(token: string) {
  const userId = await getValidSession(token)
  if (!userId) return null
  return prisma.user.findUnique({
    where: { id: userId },
    select: { id: true, username: true, role: true, mustChangePassword: true, createdAt: true, baseline: true },
  })
}
