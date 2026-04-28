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

const { handleBaseline } = await import('./routes/baseline.js')

function reset() {
  mock.clearAllMocks()
  requireAuthMock.mockResolvedValue({ userId: mockUserId, role: 'user' })
  userMock.findUnique.mockResolvedValue(userWithoutBaseline)
  userMock.update.mockImplementation(async (a: any) => ({
    baseline: a.data.baseline,
  }))
}

beforeEach(reset)

function req(path: string, opts?: RequestInit) {
  return new Request('http://localhost' + path, {
    headers: { authorization: 'Bearer tok' },
    ...opts,
  })
}

describe('handleBaseline', () => {
  it('returns null for non-baseline path', async () => {
    expect(await handleBaseline(req('/api/other'), '/api/other')).toBeNull()
  })

  it('GET /api/baseline returns needsBaseline true when no baseline', async () => {
    const res = await handleBaseline(req('/api/baseline'), '/api/baseline')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.needsBaseline).toBe(true)
    expect(body.baseline).toBeNull()
  })

  it('GET /api/baseline returns interview state with categories and questions', async () => {
    const res = await handleBaseline(req('/api/baseline'), '/api/baseline')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.interview).toBeDefined()
    expect(body.interview.total).toBe(8)
    expect(body.interview.answered).toBe(0)
    expect(Array.isArray(body.interview.categories)).toBe(true)
    expect(body.interview.categories.length).toBe(8)
  })

  it('GET /api/baseline interview categories include question prompts', async () => {
    const res = await handleBaseline(req('/api/baseline'), '/api/baseline')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    const conditions = body.interview.categories.find((c: any) => c.category === 'conditions')
    expect(conditions.question).toBeDefined()
    expect(conditions.question.length).toBeGreaterThan(10)
    expect(conditions.answered).toBe(false)
  })

  it('GET /api/baseline returns nextCategory when incomplete', async () => {
    const res = await handleBaseline(req('/api/baseline'), '/api/baseline')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.interview.nextCategory).toBe('conditions')
  })

  it('GET /api/baseline returns completed baseline with interview state', async () => {
    userMock.findUnique.mockResolvedValue(userWithBaseline)
    const res = await handleBaseline(req('/api/baseline'), '/api/baseline')
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.needsBaseline).toBe(false)
    expect(body.baseline.conditions).toBe('Type 2 diabetes')
    expect(body.interview.completed).toBe(true)
    expect(body.interview.answered).toBe(8)
    expect(body.interview.nextCategory).toBeNull()
  })

  it('POST /api/baseline with single category merges correctly', async () => {
    userMock.findUnique.mockResolvedValue(userWithoutBaseline)
    const res = await handleBaseline(
      req('/api/baseline', {
        method: 'POST',
        body: JSON.stringify({ category: 'conditions', response: 'Type 2 diabetes' }),
      }),
      '/api/baseline',
    )
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.baseline.conditions).toBe('Type 2 diabetes')
    expect(body.needsBaseline).toBe(true)
    expect(body.interview.answered).toBe(1)
    expect(body.interview.nextCategory).toBe('meds')
  })

  it('POST /api/baseline with full baseline marks as complete', async () => {
    userMock.findUnique.mockResolvedValue(userWithoutBaseline)
    const res = await handleBaseline(
      req('/api/baseline', {
        method: 'POST',
        body: JSON.stringify({
          conditions: 'Diabetes',
          meds: 'Metformin',
          allergies: 'Penicillin',
          fitness: 'Moderate',
          mentalHealth: 'Good',
          vision: 'Normal',
          chronicPain: 'None',
          diet: 'Low sodium',
        }),
      }),
      '/api/baseline',
    )
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.baseline.completed).toBe(true)
    expect(body.needsBaseline).toBe(false)
    expect(body.interview.completed).toBe(true)
  })

  it('POST /api/baseline with empty body returns 400', async () => {
    const res = await handleBaseline(
      req('/api/baseline', {
        method: 'POST',
        body: JSON.stringify({}),
      }),
      '/api/baseline',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/baseline with whitespace-only full body returns 400', async () => {
    const res = await handleBaseline(
      req('/api/baseline', {
        method: 'POST',
        body: JSON.stringify({ conditions: '   ' }),
      }),
      '/api/baseline',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/baseline full update does not overwrite existing with whitespace', async () => {
    const partial = {
      id: mockUserId,
      baseline: JSON.stringify({
        conditions: 'Diabetes',
        meds: 'Metformin',
        completed: false,
        updatedAt: '2024-01-15T10:00:00.000Z',
      }),
    }
    userMock.findUnique.mockResolvedValue(partial)

    const res = await handleBaseline(
      req('/api/baseline', {
        method: 'POST',
        body: JSON.stringify({ conditions: 'Diabetes', meds: '   ' }),
      }),
      '/api/baseline',
    )
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.baseline.conditions).toBe('Diabetes')
    expect(body.baseline.meds).toBe('Metformin')
  })

  it('POST /api/baseline with invalid category returns 400', async () => {
    const res = await handleBaseline(
      req('/api/baseline', {
        method: 'POST',
        body: JSON.stringify({ category: 'invalid', response: 'test' }),
      }),
      '/api/baseline',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/baseline with empty response returns 400', async () => {
    const res = await handleBaseline(
      req('/api/baseline', {
        method: 'POST',
        body: JSON.stringify({ category: 'conditions', response: '' }),
      }),
      '/api/baseline',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/baseline with whitespace-only response returns 400', async () => {
    const res = await handleBaseline(
      req('/api/baseline', {
        method: 'POST',
        body: JSON.stringify({ category: 'conditions', response: '   ' }),
      }),
      '/api/baseline',
    )
    expect(res!.status).toBe(400)
  })

  it('POST /api/baseline merges with existing partial baseline', async () => {
    const partial = {
      id: mockUserId,
      baseline: JSON.stringify({
        conditions: 'Diabetes',
        completed: false,
        updatedAt: '2024-01-15T10:00:00.000Z',
      }),
    }
    userMock.findUnique.mockResolvedValue(partial)

    const res = await handleBaseline(
      req('/api/baseline', {
        method: 'POST',
        body: JSON.stringify({ category: 'meds', response: 'Metformin' }),
      }),
      '/api/baseline',
    )
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.baseline.conditions).toBe('Diabetes')
    expect(body.baseline.meds).toBe('Metformin')
    expect(body.needsBaseline).toBe(true)
    expect(body.interview.answered).toBe(2)
  })

  it('POST /api/baseline returns interview state after submit', async () => {
    userMock.findUnique.mockResolvedValue(userWithoutBaseline)
    const res = await handleBaseline(
      req('/api/baseline', {
        method: 'POST',
        body: JSON.stringify({ category: 'allergies', response: 'Penicillin' }),
      }),
      '/api/baseline',
    )
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.interview).toBeDefined()
    expect(body.interview.answered).toBe(1)
    expect(body.interview.nextCategory).toBe('conditions')
  })

  it('DELETE /api/baseline resets baseline', async () => {
    userMock.findUnique.mockResolvedValue(userWithBaseline)
    const res = await handleBaseline(
      req('/api/baseline', { method: 'DELETE' }),
      '/api/baseline',
    )
    expect(res!.status).toBe(200)
    const body = await res!.json()
    expect(body.ok).toBe(true)
    expect(body.needsBaseline).toBe(true)
  })

  it('isolates baseline by userId', async () => {
    await handleBaseline(req('/api/baseline'), '/api/baseline')
    const call = userMock.findUnique.mock.calls[0]!
    expect(call[0].where.id).toBe(mockUserId)
  })
})
