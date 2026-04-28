import { describe, it, expect, beforeEach, mock } from 'bun:test'

const mockUserId = 'user-test-123'

const userWithBaseline = {
  id: mockUserId,
  baseline: JSON.stringify({
    conditions: 'Type 2 diabetes',
    meds: 'Metformin 500mg',
    allergies: 'Penicillin',
    fitness: 'Moderate',
    mentalHealth: 'Occasional anxiety',
    vision: 'Corrected to 20/20',
    chronicPain: 'Lower back',
    diet: 'Low sodium',
    completed: true,
    updatedAt: '2024-01-15T10:00:00.000Z',
  }),
}

const userWithoutBaseline = {
  id: mockUserId,
  baseline: null,
}

const userMock = {
  findUnique: mock(),
  update: mock(),
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
  prisma: { user: userMock, journalEntry: journalEntryMock, checkIn: checkInMock },
}))

mock.module('./auth.js', () => ({
  requireAuth: requireAuthMock,
}))

const { handleCheckins } = await import('./routes/checkins.js')

function reset() {
  mock.clearAllMocks()
  requireAuthMock.mockResolvedValue({ userId: mockUserId, role: 'user' })
  userMock.findUnique.mockResolvedValue(userWithoutBaseline)
  journalEntryMock.findMany.mockResolvedValue([])
  checkInMock.findFirst.mockResolvedValue(null)
  checkInMock.findMany.mockResolvedValue([])
  checkInMock.count.mockResolvedValue(0)
  checkInMock.create.mockImplementation(async (data: any) => ({
    id: 'checkin-123',
    userId: mockUserId,
    questions: data.data.questions,
    responses: data.data.responses,
    mentalScore: data.data.mentalScore ?? null,
    physicalScore: data.data.physicalScore ?? null,
    staminaScore: data.data.staminaScore ?? null,
    date: data.data.date,
    aiSummary: null,
    categories: null,
    createdAt: new Date(),
  }))
}

beforeEach(reset)

function req(path: string, opts?: RequestInit) {
  return new Request('http://localhost' + path, {
    headers: { authorization: 'Bearer tok' },
    ...opts,
  })
}

describe('handleCheckins', () => {
  it('returns null for non-checkins path', async () => {
    expect(await handleCheckins(req('/api/other'), '/api/other')).toBeNull()
  })

  it('GET /api/checkins/prompt returns questions', async () => {
    const res = await handleCheckins(req('/api/checkins/prompt'), '/api/checkins/prompt')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.questions).toBeDefined()
    expect(Object.keys(body.questions).length).toBeGreaterThan(0)
  })

  it('GET /api/checkins/prompt includes baseline-specific questions', async () => {
    userMock.findUnique.mockResolvedValue(userWithBaseline)
    const res = await handleCheckins(req('/api/checkins/prompt'), '/api/checkins/prompt')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.questions.conditions).toBeDefined()
    expect(body.questions.chronicPain).toBeDefined()
    expect(body.questions.mentalHealth).toBeDefined()
  })

  it('GET /api/checkins/prompt includes context', async () => {
    const res = await handleCheckins(req('/api/checkins/prompt'), '/api/checkins/prompt')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.context).toBeDefined()
    expect(body.context.baseline).toBeNull()
    expect(Array.isArray(body.context.recentJournal)).toBe(true)
  })

  it('POST /api/checkins/respond creates checkin with scores', async () => {
    const res = await handleCheckins(
      req('/api/checkins/respond', {
        method: 'POST',
        body: JSON.stringify({
          questions: { mood: 'How are you?' },
          responses: { mood: 'Feeling good today' },
        }),
      }),
      '/api/checkins/respond',
    )
    expect(res!.status).toBe(201)
    const body = await res!.json()
    expect(body.checkin).toBeDefined()
    expect(body.scores).toBeDefined()
    expect(body.scores.mentalScore).toBeGreaterThanOrEqual(1)
    expect(body.scores.mentalScore).toBeLessThanOrEqual(10)
    expect(body.scores.physicalScore).toBeGreaterThanOrEqual(1)
    expect(body.scores.staminaScore).toBeGreaterThanOrEqual(1)
  })

  it('POST /api/checkins/respond with negative keywords lowers scores', async () => {
    const res = await handleCheckins(
      req('/api/checkins/respond', {
        method: 'POST',
        body: JSON.stringify({
          questions: { mood: 'How are you?' },
          responses: { mood: 'Feeling anxious and depressed with pain' },
        }),
      }),
      '/api/checkins/respond',
    )
    expect(res!.status).toBe(201)
    const body = await res!.json()
    expect(body.scores.mentalScore).toBeLessThan(5)
    expect(body.scores.physicalScore).toBeLessThan(5)
  })

  it('POST /api/checkins/respond with empty responses returns 400', async () => {
    const res = await handleCheckins(
      req('/api/checkins/respond', {
        method: 'POST',
        body: JSON.stringify({
          questions: { mood: 'How are you?' },
          responses: {},
        }),
      }),
      '/api/checkins/respond',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/checkins/respond with skipped=true allows empty responses', async () => {
    const res = await handleCheckins(
      req('/api/checkins/respond', {
        method: 'POST',
        body: JSON.stringify({
          questions: { mood: 'How are you?' },
          responses: {},
          skipped: true,
        }),
      }),
      '/api/checkins/respond',
    )
    expect(res!.status).toBe(201)
  })

  it('POST /api/checkins/skip creates skipped checkin', async () => {
    const res = await handleCheckins(
      req('/api/checkins/skip', {
        method: 'POST',
        body: JSON.stringify({}),
      }),
      '/api/checkins/skip',
    )
    expect(res!.status).toBe(201)
    const body = await res!.json()
    expect(body.skipped).toBe(true)
    expect(body.checkin).toBeDefined()
  })

  it('POST /api/checkins/respond with promptId references existing checkin', async () => {
    const originalQuestions = JSON.stringify({ mood: 'How are you?' })
    checkInMock.findFirst.mockResolvedValue({
      id: 'prompt-123',
      questions: originalQuestions,
    })

    const res = await handleCheckins(
      req('/api/checkins/respond', {
        method: 'POST',
        body: JSON.stringify({
          promptId: 'prompt-123',
          responses: { mood: 'Great' },
        }),
      }),
      '/api/checkins/respond',
    )
    expect(res!.status).toBe(201)
    const body = await res!.json()
    const questions = body.checkin.questions
    expect(typeof questions).toBe('object')
    expect(questions.mood).toBe('How are you?')
  })

  it('POST /api/checkins/respond with missing promptId returns 404', async () => {
    checkInMock.findFirst.mockResolvedValue(null)

    const res = await handleCheckins(
      req('/api/checkins/respond', {
        method: 'POST',
        body: JSON.stringify({
          promptId: 'nonexistent',
          responses: { mood: 'Great' },
        }),
      }),
      '/api/checkins/respond',
    )
    expect(res!.status).toBe(404)
  })

  it('POST /api/checkins/respond with missing promptId returns 404', async () => {
    checkInMock.findFirst.mockResolvedValue(null)

    const res = await handleCheckins(
      req('/api/checkins/respond', {
        method: 'POST',
        body: JSON.stringify({
          promptId: 'nonexistent',
          responses: { mood: 'Great' },
        }),
      }),
      '/api/checkins/respond',
    )
    expect(res!.status).toBe(404)
  })

  it('GET /api/checkins returns existing checkins', async () => {
    checkInMock.findMany.mockResolvedValue([
      {
        id: 'checkin-1',
        date: new Date(),
        questions: JSON.stringify({ mood: 'How are you?' }),
        responses: JSON.stringify({ mood: 'Good' }),
        mentalScore: 7,
        physicalScore: 8,
        staminaScore: 6,
        aiSummary: null,
        categories: null,
        createdAt: new Date(),
      },
    ])
    checkInMock.count.mockResolvedValue(1)

    const res = await handleCheckins(req('/api/checkins'), '/api/checkins')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.checkins.length).toBe(1)
    expect(body.checkins[0].questions.mood).toBe('How are you?')
    expect(body.checkins[0].responses.mood).toBe('Good')
  })

  it('POST /api/checkins creates checkin directly', async () => {
    const res = await handleCheckins(
      req('/api/checkins', {
        method: 'POST',
        body: JSON.stringify({
          questions: { mood: 'How are you?' },
          responses: { mood: 'Good' },
          mentalScore: 7,
          physicalScore: 8,
          staminaScore: 6,
        }),
      }),
      '/api/checkins',
    )
    expect(res!.status).toBe(201)
    const body = await res!.json()
    expect(body.checkin).toBeDefined()
  })

  it('isolates checkins by userId', async () => {
    await handleCheckins(req('/api/checkins/prompt'), '/api/checkins/prompt')
    expect(userMock.findUnique.mock.calls.length).toBeGreaterThan(0)
    const call = userMock.findUnique.mock.calls[0]!
    expect(call[0].where.id).toBe(mockUserId)
  })
})
