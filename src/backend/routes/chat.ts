import { requireAuth } from '../auth.js'
import { prisma } from '../db.js'
import { parsePagination } from '../utils/pagination.js'
import { chatMessageCreateSchema, chatSessionCreateSchema } from '../utils/schemas.js'
import { chatService, gatherChatContext } from '../chatService.js'

const rateLimitStore = new Map<string, { count: number; reset: number }>()
const RATE_LIMIT_MAX = 20
const RATE_LIMIT_WINDOW = 60_000

export function resetRateLimitStore(): void {
  rateLimitStore.clear()
}

function checkRateLimit(userId: string): boolean {
  const now = Date.now()
  if (rateLimitStore.size > 1000) {
    pruneExpiredRateLimits()
  }
  const entry = rateLimitStore.get(userId)
  if (!entry || now > entry.reset) {
    rateLimitStore.set(userId, { count: 1, reset: now + RATE_LIMIT_WINDOW })
    return true
  }
  if (entry.count >= RATE_LIMIT_MAX) {
    return false
  }
  entry.count++
  return true
}

function pruneExpiredRateLimits(): void {
  const now = Date.now()
  for (const [key, entry] of rateLimitStore.entries()) {
    if (now > entry.reset) {
      rateLimitStore.delete(key)
    }
  }
}

export async function handleChat(req: Request, path: string): Promise<Response | null> {
  const pathname = path.split('?')[0]!
  const parts = pathname.split('/').filter(Boolean)
  if (parts[1] !== 'chat') return null

  try {
    if (parts.length === 3 && parts[2] === 'sessions' && req.method === 'GET') return await listSessions(req)
    if (parts.length === 3 && parts[2] === 'sessions' && req.method === 'POST') return await createSession(req)
    if (parts.length === 4 && parts[2] === 'sessions' && req.method === 'DELETE') return await deleteSession(req, parts[3]!)
    if (parts.length === 5 && parts[2] === 'sessions' && parts[4] === 'messages' && req.method === 'GET') return await listMessages(req, parts[3]!)
    if (parts.length === 5 && parts[2] === 'sessions' && parts[4] === 'messages' && req.method === 'POST') return await sendMessage(req, parts[3]!)
    
    return Response.json({ error: 'not found' }, { status: 404 })
  } catch (err: any) {
    if (err.message === 'missing token' || err.message === 'invalid token' || err.message === 'user not found') {
      return Response.json({ error: err.message }, { status: 401 })
    }
    console.error('Chat API Error:', err)
    return Response.json({ error: 'internal server error' }, { status: 500 })
  }
}

async function listSessions(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const { limit, offset } = parsePagination(new URL(req.url))

  const [sessions, total] = await Promise.all([
    prisma.chatSession.findMany({
      where: { userId: ctx.userId },
      orderBy: { updatedAt: 'desc' },
      take: limit,
      skip: offset,
      select: { id: true, title: true, createdAt: true, updatedAt: true },
    }),
    prisma.chatSession.count({ where: { userId: ctx.userId } }),
  ])

  return Response.json({ sessions, total, limit, offset })
}

async function createSession(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const body = await req.json().catch(() => ({}))
  const result = chatSessionCreateSchema.safeParse(body)
  if (!result.success) {
    return Response.json({ error: result.error.issues.map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`).join('; ') }, { status: 400 })
  }

  const session = await prisma.chatSession.create({
    data: {
      userId: ctx.userId,
      title: result.data.title || 'New Chat',
    },
    select: { id: true, title: true, createdAt: true, updatedAt: true },
  })

  return Response.json({ session }, { status: 201 })
}

async function deleteSession(req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(req)
  const result = await prisma.chatSession.deleteMany({ where: { id, userId: ctx.userId } })
  if (result.count === 0) return Response.json({ error: 'not found' }, { status: 404 })
  return Response.json({ ok: true })
}

async function listMessages(req: Request, sessionId: string): Promise<Response> {
  const ctx = await requireAuth(req)
  
  const session = await prisma.chatSession.findFirst({ where: { id: sessionId, userId: ctx.userId } })
  if (!session) return Response.json({ error: 'not found' }, { status: 404 })

  const { limit, offset } = parsePagination(new URL(req.url))

  const [messages, total] = await Promise.all([
    prisma.chatMessage.findMany({
      where: { sessionId, userId: ctx.userId },
      orderBy: { createdAt: 'desc' },
      take: limit,
      skip: offset,
      select: { id: true, role: true, content: true, sources: true, images: true, createdAt: true },
    }),
    prisma.chatMessage.count({ where: { sessionId, userId: ctx.userId } }),
  ])

  return Response.json({ messages, total, limit, offset })
}

async function sendMessage(req: Request, sessionId: string): Promise<Response> {
  const ctx = await requireAuth(req)

  const session = await prisma.chatSession.findFirst({ where: { id: sessionId, userId: ctx.userId } })
  if (!session) return Response.json({ error: 'not found' }, { status: 404 })

  if (!checkRateLimit(ctx.userId)) {
    return Response.json({ error: 'rate limit exceeded' }, { status: 429 })
  }

  const body = await req.json().catch(() => ({}))
  const result = chatMessageCreateSchema.safeParse(body)
  if (!result.success) {
    return Response.json({ error: result.error.issues.map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`).join('; ') }, { status: 400 })
  }

  if (result.data.sessionId !== sessionId) {
    return Response.json({ error: 'session id mismatch' }, { status: 400 })
  }

  const wantsStream = new URL(req.url).searchParams.get('stream') === '1' && typeof chatService.streamReply === 'function'
  if (wantsStream) {
    return await streamMessage(ctx.userId, sessionId, result.data)
  }

  const { message, sources, images } = result.data

  const [context, history] = await Promise.all([
    gatherChatContext(ctx.userId),
    prisma.chatMessage.findMany({
      where: { sessionId, userId: ctx.userId },
      orderBy: { createdAt: 'desc' },
      take: 12,
      select: { role: true, content: true },
    }),
  ])

  const historyReversed = history.reverse().map((m: { role: string; content: string }) => ({ role: m.role, content: m.content }))

  let reply: { content: string }
  try {
    reply = await chatService.generateReply(message, context, historyReversed)
  } catch (err: any) {
    reply = { content: `Sorry, I encountered an error processing your request: ${err.message || 'unknown error'}` }
  }

  const now = new Date()
  const userTs = now
  const assistantTs = new Date(now.getTime() + 1)

  const [, assistantMsg] = await prisma.$transaction([
    prisma.chatMessage.create({
      data: {
        userId: ctx.userId,
        sessionId,
        role: 'user',
        content: message,
        sources: sources ? JSON.stringify(sources) : null,
        images: images ? JSON.stringify(images) : null,
        createdAt: userTs,
      },
      select: { id: true, role: true, content: true, sources: true, images: true, createdAt: true },
    }),
    prisma.chatMessage.create({
      data: {
        userId: ctx.userId,
        sessionId,
        role: 'assistant',
        content: reply.content,
        createdAt: assistantTs,
      },
      select: { id: true, role: true, content: true, sources: true, images: true, createdAt: true },
    }),
  ])

  await prisma.chatSession.update({
    where: { id: sessionId },
    data: { updatedAt: assistantTs },
  })

  if (historyReversed.length === 0 && chatService.inferTitle) {
    chatService.inferTitle(message, reply.content).then(async (title) => {
      if (title) {
        await prisma.chatSession.update({
          where: { id: sessionId },
          data: { title: title.replace(/["']/g, '') }, // clean quotes if any
        })
      }
    }).catch(console.error)
  }

  return Response.json({ message: assistantMsg }, { status: 201 })
}

async function streamMessage(
  userId: string,
  sessionId: string,
  data: { message: string; sources?: any; images?: any },
): Promise<Response> {
  const { message, sources: userSources, images } = data

  const [context, history] = await Promise.all([
    gatherChatContext(userId),
    prisma.chatMessage.findMany({
      where: { sessionId, userId },
      orderBy: { createdAt: 'desc' },
      take: 12,
      select: { role: true, content: true },
    }),
  ])

  const historyReversed = history.reverse().map((m: { role: string; content: string }) => ({ role: m.role, content: m.content }))

  const now = new Date()
  const userTs = now
  const assistantTs = new Date(now.getTime() + 1)

  const userMsg = await prisma.chatMessage.create({
    data: {
      userId,
      sessionId,
      role: 'user',
      content: message,
      sources: userSources ? JSON.stringify(userSources) : null,
      images: images ? JSON.stringify(images) : null,
      createdAt: userTs,
    },
    select: { id: true, role: true, content: true, sources: true, images: true, createdAt: true },
  })

  const encoder = new TextEncoder()
  let assistantSources: any[] = []
  let assistantContent = ''
  let savedMessageId: string | null = null
  let pendingSave: Promise<any> = Promise.resolve()
  let clientConnected = true

  const saveAssistantMessage = () => {
    pendingSave = pendingSave.then(async () => {
      if (!assistantContent.trim() && assistantSources.length === 0) return null
      try {
        if (savedMessageId) {
          const updated = await prisma.chatMessage.update({
            where: { id: savedMessageId },
            data: {
              content: assistantContent.trim(),
              sources: assistantSources.length > 0 ? JSON.stringify(assistantSources) : null,
            },
            select: { id: true, role: true, content: true, sources: true, images: true, createdAt: true },
          })
          await prisma.chatSession.update({
            where: { id: sessionId },
            data: { updatedAt: new Date() },
          })
          return updated
        }
        const assistantMsg = await prisma.chatMessage.create({
          data: {
            userId,
            sessionId,
            role: 'assistant',
            content: assistantContent.trim(),
            sources: assistantSources.length > 0 ? JSON.stringify(assistantSources) : null,
            createdAt: assistantTs,
          },
          select: { id: true, role: true, content: true, sources: true, images: true, createdAt: true },
        })
        savedMessageId = assistantMsg.id
        await prisma.chatSession.update({
          where: { id: sessionId },
          data: { updatedAt: assistantTs },
        })
        return assistantMsg
      } catch (err) {
        console.error('Failed to save assistant message:', err)
        return null
      }
    })
    return pendingSave
  }

  const send = (controller: ReadableStreamDefaultController, event: any) => {
    if (!clientConnected) return
    try {
      controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
    } catch {
      clientConnected = false
    }
  }

  // Run LLM generation to completion regardless of client connection.
  // On a single-user RK1, a disconnect is almost always a refresh,
  // not an intentional cancellation. Save the full response.
  const generationDone = (async (controller: ReadableStreamDefaultController) => {
    try {
      send(controller, { type: 'user_message', message: userMsg })

      const gen = chatService.streamReply!(message, context, historyReversed)
      for await (const ev of gen) {
        if (ev.type === 'sources') {
          assistantSources = ev.sources
          send(controller, { type: 'sources', sources: ev.sources })
        } else if (ev.type === 'delta') {
          assistantContent += ev.content
          send(controller, { type: 'delta', content: ev.content })
        } else if (ev.type === 'error') {
          send(controller, { type: 'error', message: ev.message })
        } else if (ev.type === 'done') {
          break
        }
      }

      const assistantMsg = await saveAssistantMessage()
      if (assistantMsg) send(controller, { type: 'done', message: assistantMsg })

      if (historyReversed.length === 0 && chatService.inferTitle) {
        try {
          const title = await chatService.inferTitle(message, assistantContent)
          if (title) {
            const cleanTitle = title.replace(/["']/g, '')
            await prisma.chatSession.update({
              where: { id: sessionId },
              data: { title: cleanTitle },
            })
            send(controller, { type: 'title', title: cleanTitle, sessionId })
          }
        } catch (e) {
          console.error('Title inference failed:', e)
        }
      }
    } catch (err: any) {
      console.error('Stream error:', err)
      send(controller, { type: 'error', message: err?.message || 'stream failed' })
    } finally {
      await saveAssistantMessage()
      if (clientConnected) {
        try { controller.close() } catch {}
      }
    }
  })

  let resolveController: (c: ReadableStreamDefaultController) => void
  const controllerReady = new Promise<ReadableStreamDefaultController>(r => { resolveController = r })

  const stream = new ReadableStream({
    start(controller) {
      resolveController!(controller)
    },
    cancel() {
      clientConnected = false
      saveAssistantMessage().catch(console.error)
    },
  })

  controllerReady.then(c => generationDone(c))

  return new Response(stream, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}
