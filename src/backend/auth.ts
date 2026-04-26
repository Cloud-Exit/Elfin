import { prisma } from './db.js'

export type AuthContext = { userId: string; role: string }

const sessions = new Map<string, string>() // token -> userId

export async function hashPassword(password: string): Promise<string> {
  return Bun.password.hash(password, { algorithm: 'bcrypt', cost: 12 })
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  return Bun.password.verify(password, hash)
}

export function createToken(): string {
  return crypto.randomUUID()
}

export function setSession(token: string, userId: string): void {
  sessions.set(token, userId)
}

export function clearSession(token: string): void {
  sessions.delete(token)
}

export async function requireAuth(req: Request): Promise<AuthContext> {
  const auth = req.headers.get('authorization') ?? ''
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : auth
  if (!token) throw new Error('missing token')

  const userId = sessions.get(token)
  if (!userId) throw new Error('invalid token')

  const user = await prisma.user.findUnique({ where: { id: userId } })
  if (!user) throw new Error('user not found')

  return { userId: user.id, role: user.role }
}

export async function getUserFromToken(token: string) {
  const userId = sessions.get(token)
  if (!userId) return null
  return prisma.user.findUnique({
    where: { id: userId },
    select: { id: true, username: true, role: true, mustChangePassword: true, createdAt: true, baseline: true },
  })
}
