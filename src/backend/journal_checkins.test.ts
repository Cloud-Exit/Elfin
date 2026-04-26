import { describe, it, expect, beforeEach, mock } from 'bun:test'

const mockUserId = 'user-test-123'

const entry = {
  id: 'entry-1',
  userId: mockUserId,
  content: 'Test journal entry',
  date: new Date('2024-01-15T10:00:00Z'),
  aiSummary: null,
  aiCategories: null,
  createdAt: new Date('2024-01-15T10:00:00Z'),
}

const checkin = {
  id: 'checkin-1',
  userId: mockUserId,
  date: new Date('2024-01-15T10:00:00Z'),
  questions: JSON.stringify({ q1: 'How are you?' }),
  responses: JSON.stringify({ q1: 'Good' }),
  aiSummary: null,
  mentalScore: 7,
  physicalScore: 8,
  staminaScore: 6,
  categories: null,
  createdAt: new Date('2024-01-15T10:00:00Z'),
}

const journalEntryMock = {
  findMany: mock(),
  count: mock(),
  create: mock(),
  findFirst: mock(),
  update: mock(),
  delete: mock(),
}

const checkInMock = {
  findMany: mock(),
  count: mock(),
  create: mock(),
  findFirst: mock(),
  update: mock(),
  delete: mock(),
}

const requireAuthMock = mock()

mock.module('./db.js', () => ({
  prisma: { journalEntry: journalEntryMock, checkIn: checkInMock },
}))

mock.module('./auth.js', () => ({
  requireAuth: requireAuthMock,
}))

const { handleJournal } = await import('./routes/journal.js')
const { handleCheckins } = await import('./routes/checkins.js')

function reset() {
  mock.clearAllMocks()
  requireAuthMock.mockResolvedValue({ userId: mockUserId, role: 'user' })
  journalEntryMock.findMany.mockResolvedValue([entry])
  journalEntryMock.count.mockResolvedValue(1)
  journalEntryMock.create.mockImplementation(async (a: any) => ({ ...entry, ...a.data }))
  journalEntryMock.findFirst.mockResolvedValue(entry)
  journalEntryMock.update.mockImplementation(async (a: any) => ({ ...entry, ...a.data }))
  journalEntryMock.delete.mockResolvedValue({})
  checkInMock.findMany.mockResolvedValue([checkin])
  checkInMock.count.mockResolvedValue(1)
  checkInMock.create.mockImplementation(async (a: any) => ({ ...checkin, ...a.data }))
  checkInMock.findFirst.mockResolvedValue(checkin)
  checkInMock.update.mockImplementation(async (a: any) => ({ ...checkin, ...a.data }))
  checkInMock.delete.mockResolvedValue({})
}

beforeEach(reset)

function req(path: string, opts?: RequestInit) {
  return new Request('http://localhost' + path, {
    headers: { authorization: 'Bearer tok' },
    ...opts,
  })
}

describe('handleJournal', () => {
  it('returns null for non-journal path', async () => {
    expect(await handleJournal(req('/api/other'), '/api/other')).toBeNull()
  })

  it('GET /api/journal defaults to limit=50, offset=0', async () => {
    const res = await handleJournal(req('/api/journal'), '/api/journal')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.limit).toBe(50)
    expect(body.offset).toBe(0)
    expect(Array.isArray(body.entries)).toBe(true)
    expect(body.total).toBe(1)
  })

  it('GET /api/journal?limit=10&offset=20 respects params', async () => {
    const res = await handleJournal(
      req('/api/journal?limit=10&offset=20'),
      '/api/journal?limit=10&offset=20',
    )
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.limit).toBe(10)
    expect(body.offset).toBe(20)
  })

  it('GET /api/journal?limit=abc returns 400', async () => {
    const res = await handleJournal(req('/api/journal?limit=abc'), '/api/journal?limit=abc')
    expect(res!.status).toBe(400)
  })

  it('GET /api/journal?limit=-5 returns 400', async () => {
    const res = await handleJournal(req('/api/journal?limit=-5'), '/api/journal?limit=-5')
    expect(res!.status).toBe(400)
  })

  it('GET /api/journal?limit=0 returns 400', async () => {
    const res = await handleJournal(req('/api/journal?limit=0'), '/api/journal?limit=0')
    expect(res!.status).toBe(400)
  })

  it('GET /api/journal?limit=300 clamps to 200', async () => {
    const res = await handleJournal(req('/api/journal?limit=300'), '/api/journal?limit=300')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.limit).toBe(200)
  })

  it('GET /api/journal?offset=-1 returns 400', async () => {
    const res = await handleJournal(req('/api/journal?offset=-1'), '/api/journal?offset=-1')
    expect(res!.status).toBe(400)
  })

  it('GET /api/journal?offset=xyz returns 400', async () => {
    const res = await handleJournal(req('/api/journal?offset=xyz'), '/api/journal?offset=xyz')
    expect(res!.status).toBe(400)
  })

  it('GET /api/journal?limit=1.5 rejects decimal', async () => {
    const res = await handleJournal(req('/api/journal?limit=1.5'), '/api/journal?limit=1.5')
    expect(res!.status).toBe(400)
  })

  it('GET /api/journal?offset=2.5 rejects decimal', async () => {
    const res = await handleJournal(req('/api/journal?offset=2.5'), '/api/journal?offset=2.5')
    expect(res!.status).toBe(400)
  })

  it('POST /api/journal without content returns 400', async () => {
    const res = await handleJournal(
      req('/api/journal', { method: 'POST', body: JSON.stringify({}) }),
      '/api/journal',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/journal with empty string content returns 400', async () => {
    const res = await handleJournal(
      req('/api/journal', { method: 'POST', body: JSON.stringify({ content: '' }) }),
      '/api/journal',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/journal with whitespace-only content returns 400', async () => {
    const res = await handleJournal(
      req('/api/journal', { method: 'POST', body: JSON.stringify({ content: '   ' }) }),
      '/api/journal',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/journal with content returns 201', async () => {
    const res = await handleJournal(
      req('/api/journal', { method: 'POST', body: JSON.stringify({ content: 'My day' }) }),
      '/api/journal',
    )
    expect(res!.status).toBe(201)
    const body = await res!.json()
    expect(body.entry.content).toBe('My day')
  })

  it('GET /api/journal/:id returns entry', async () => {
    const res = await handleJournal(req('/api/journal/e1'), '/api/journal/e1')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.entry.id).toBe('entry-1')
  })

  it('GET /api/journal/:id returns 404 when not found', async () => {
    journalEntryMock.findFirst.mockResolvedValueOnce(null)
    const res = await handleJournal(req('/api/journal/missing'), '/api/journal/missing')
    expect(res!.status).toBe(404)
  })

  it('PUT /api/journal/:id updates entry', async () => {
    const res = await handleJournal(
      req('/api/journal/e1', { method: 'PUT', body: JSON.stringify({ content: 'updated' }) }),
      '/api/journal/e1',
    )
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.entry.content).toBe('updated')
  })

  it('PUT /api/journal/:id returns 404 when not found', async () => {
    journalEntryMock.findFirst.mockResolvedValueOnce(null)
    const res = await handleJournal(
      req('/api/journal/missing', { method: 'PUT', body: JSON.stringify({ content: 'x' }) }),
      '/api/journal/missing',
    )
    expect(res!.status).toBe(404)
  })

  it('DELETE /api/journal/:id succeeds', async () => {
    const res = await handleJournal(
      req('/api/journal/e1', { method: 'DELETE' }),
      '/api/journal/e1',
    )
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.ok).toBe(true)
  })

  it('DELETE /api/journal/:id returns 404 when not found', async () => {
    journalEntryMock.findFirst.mockResolvedValueOnce(null)
    const res = await handleJournal(
      req('/api/journal/missing', { method: 'DELETE' }),
      '/api/journal/missing',
    )
    expect(res!.status).toBe(404)
  })

  it('isolates entries by userId', async () => {
    await handleJournal(req('/api/journal'), '/api/journal')
    const call = journalEntryMock.findMany.mock.calls[0]![0]
    expect(call.where.userId).toBe(mockUserId)
  })
})

describe('handleCheckins', () => {
  it('returns null for non-checkin path', async () => {
    expect(await handleCheckins(req('/api/other'), '/api/other')).toBeNull()
  })

  it('GET /api/checkins defaults to limit=50, offset=0', async () => {
    const res = await handleCheckins(req('/api/checkins'), '/api/checkins')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.limit).toBe(50)
    expect(body.offset).toBe(0)
    expect(Array.isArray(body.checkins)).toBe(true)
  })

  it('GET /api/checkins decodes questions/responses to objects', async () => {
    const res = await handleCheckins(req('/api/checkins'), '/api/checkins')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(typeof body.checkins[0].questions).toBe('object')
    expect(typeof body.checkins[0].responses).toBe('object')
    expect(body.checkins[0].questions.q1).toBe('How are you?')
  })

  it('GET /api/checkins?limit=abc returns 400', async () => {
    const res = await handleCheckins(req('/api/checkins?limit=abc'), '/api/checkins?limit=abc')
    expect(res!.status).toBe(400)
  })

  it('GET /api/checkins?offset=-1 returns 400', async () => {
    const res = await handleCheckins(req('/api/checkins?offset=-1'), '/api/checkins?offset=-1')
    expect(res!.status).toBe(400)
  })

  it('GET /api/checkins?limit=1.5 rejects decimal', async () => {
    const res = await handleCheckins(req('/api/checkins?limit=1.5'), '/api/checkins?limit=1.5')
    expect(res!.status).toBe(400)
  })

  it('GET /api/checkins?offset=2.5 rejects decimal', async () => {
    const res = await handleCheckins(req('/api/checkins?offset=2.5'), '/api/checkins?offset=2.5')
    expect(res!.status).toBe(400)
  })

  it('POST /api/checkins without questions returns 400', async () => {
    const res = await handleCheckins(
      req('/api/checkins', { method: 'POST', body: JSON.stringify({ responses: {} }) }),
      '/api/checkins',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/checkins without responses returns 400', async () => {
    const res = await handleCheckins(
      req('/api/checkins', { method: 'POST', body: JSON.stringify({ questions: {} }) }),
      '/api/checkins',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/checkins valid data returns 201 with decoded objects', async () => {
    const res = await handleCheckins(
      req('/api/checkins', {
        method: 'POST',
        body: JSON.stringify({ questions: { q1: 'How?' }, responses: { q1: 'Fine' } }),
      }),
      '/api/checkins',
    )
    expect(res!.status).toBe(201)
    const body = await res!.json()
    expect(typeof body.checkin.questions).toBe('object')
    expect(typeof body.checkin.responses).toBe('object')
  })

  it('POST /api/checkins accepts optional scores', async () => {
    const res = await handleCheckins(
      req('/api/checkins', {
        method: 'POST',
        body: JSON.stringify({
          questions: { q1: 'How?' },
          responses: { q1: 'Fine' },
          mentalScore: 5,
          physicalScore: 7,
          staminaScore: 3,
        }),
      }),
      '/api/checkins',
    )
    expect(res!.status).toBe(201)
  })

  it('POST /api/checkins rejects score > 10', async () => {
    const res = await handleCheckins(
      req('/api/checkins', {
        method: 'POST',
        body: JSON.stringify({
          questions: { q1: 'How?' },
          responses: { q1: 'Fine' },
          mentalScore: 15,
        }),
      }),
      '/api/checkins',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/checkins rejects score < 1', async () => {
    const res = await handleCheckins(
      req('/api/checkins', {
        method: 'POST',
        body: JSON.stringify({
          questions: { q1: 'How?' },
          responses: { q1: 'Fine' },
          staminaScore: 0,
        }),
      }),
      '/api/checkins',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/checkins rejects questions as array', async () => {
    const res = await handleCheckins(
      req('/api/checkins', {
        method: 'POST',
        body: JSON.stringify({ questions: ['q1', 'q2'], responses: { q1: 'Fine' } }),
      }),
      '/api/checkins',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/checkins rejects responses as array', async () => {
    const res = await handleCheckins(
      req('/api/checkins', {
        method: 'POST',
        body: JSON.stringify({ questions: { q1: 'How?' }, responses: ['a', 'b'] }),
      }),
      '/api/checkins',
    )
    expect(res!.status).toBe(400)
  })

  it('GET /api/checkins/:id returns decoded objects', async () => {
    const res = await handleCheckins(req('/api/checkins/c1'), '/api/checkins/c1')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(typeof body.checkin.questions).toBe('object')
    expect(typeof body.checkin.responses).toBe('object')
  })

  it('GET /api/checkins/:id returns 404 when not found', async () => {
    checkInMock.findFirst.mockResolvedValueOnce(null)
    const res = await handleCheckins(req('/api/checkins/missing'), '/api/checkins/missing')
    expect(res!.status).toBe(404)
  })

  it('DELETE /api/checkins/:id returns 404 when not found', async () => {
    checkInMock.findFirst.mockResolvedValueOnce(null)
    const res = await handleCheckins(
      req('/api/checkins/missing', { method: 'DELETE' }),
      '/api/checkins/missing',
    )
    expect(res!.status).toBe(404)
  })

  it('isolates checkins by userId', async () => {
    await handleCheckins(req('/api/checkins'), '/api/checkins')
    const call = checkInMock.findMany.mock.calls[0]![0]
    expect(call.where.userId).toBe(mockUserId)
  })
})
