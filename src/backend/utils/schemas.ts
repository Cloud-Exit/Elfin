import { z } from 'zod'

export const paginationSchema = z.object({
  limit: z.coerce.number().int().min(1).default(50),
  offset: z.coerce.number().int().min(0).default(0),
})

export const journalCreateSchema = z.object({
  content: z.string().trim().min(1).max(50_000),
  date: z.coerce.date().optional(),
})

export const journalUpdateSchema = z.object({
  content: z.string().trim().min(1).max(50_000).optional(),
  date: z.coerce.date().optional(),
})

export const checkinCreateSchema = z.object({
  questions: z.record(z.string(), z.unknown()).refine((v) => !Array.isArray(v), { message: 'questions must be an object, not an array' }),
  responses: z.record(z.string(), z.unknown()).refine((v) => !Array.isArray(v), { message: 'responses must be an object, not an array' }),
  mentalScore: z.coerce.number().min(1).max(10).optional().nullable(),
  physicalScore: z.coerce.number().min(1).max(10).optional().nullable(),
  staminaScore: z.coerce.number().min(1).max(10).optional().nullable(),
  date: z.coerce.date().optional(),
})

export const checkinUpdateSchema = z.object({
  questions: z.record(z.string(), z.unknown()).refine((v) => !Array.isArray(v), { message: 'questions must be an object, not an array' }).optional(),
  responses: z.record(z.string(), z.unknown()).refine((v) => !Array.isArray(v), { message: 'responses must be an object, not an array' }).optional(),
  mentalScore: z.coerce.number().min(1).max(10).optional().nullable(),
  physicalScore: z.coerce.number().min(1).max(10).optional().nullable(),
  staminaScore: z.coerce.number().min(1).max(10).optional().nullable(),
  date: z.coerce.date().optional(),
})

export const baselineCategories = [
  'conditions',
  'meds',
  'allergies',
  'fitness',
  'mentalHealth',
  'vision',
  'chronicPain',
  'diet',
] as const

export type BaselineCategory = typeof baselineCategories[number]

export const baselineQuestions: Record<BaselineCategory, string> = {
  conditions: 'Do you have any pre-existing medical conditions? (e.g. diabetes, heart disease, asthma)',
  meds: 'What medications are you currently taking? Include dosages if known.',
  allergies: 'Do you have any allergies? (food, medication, environmental)',
  fitness: 'How would you describe your fitness level? (sedentary, light activity, moderate, active)',
  mentalHealth: 'Any history of mental health concerns? (anxiety, depression, PTSD, stress)',
  vision: 'How is your vision? Any corrections needed? Known issues?',
  chronicPain: 'Do you experience chronic pain? Where and how severe?',
  diet: 'Any dietary restrictions, needs, or preferences? (vegetarian, low sodium, food intolerances)',
}

export const baselineFieldsSchema = z.object({
  conditions: z.string().trim().max(2000).optional(),
  meds: z.string().trim().max(2000).optional(),
  allergies: z.string().trim().max(2000).optional(),
  fitness: z.string().trim().max(2000).optional(),
  mentalHealth: z.string().trim().max(2000).optional(),
  vision: z.string().trim().max(2000).optional(),
  chronicPain: z.string().trim().max(2000).optional(),
  diet: z.string().trim().max(2000).optional(),
})

export type BaselineFields = z.infer<typeof baselineFieldsSchema>

export const baselineSchema = baselineFieldsSchema.refine(
  (data) => baselineCategories.some((cat) => {
    const val = data[cat]
    return typeof val === 'string' && val.trim().length > 0
  }),
  { message: 'at least one category must have a response' },
)

export const baselineSubmitSchema = z.object({
  category: z.enum(baselineCategories).optional(),
  response: z.string().trim().min(1).optional(),
}).refine(
  (data) => {
    if (data.category && !data.response) return false
    return true
  },
  { message: 'response is required when category is provided', path: ['response'] },
)

export const checkinRespondSchema = z.object({
  promptId: z.string().trim().min(1).optional(),
  questions: z.record(z.string(), z.string()).optional(),
  responses: z.record(z.string(), z.string()),
  skipped: z.boolean().optional(),
}).refine(
  (data) => {
    if (!data.skipped && Object.keys(data.responses).length === 0) return false
    return true
  },
  { message: 'responses are required unless skipped is true' },
).refine(
  (data) => {
    if (!data.promptId && !data.questions) return false
    return true
  },
  { message: 'questions are required unless promptId is provided', path: ['questions'] },
)

export const chatSessionCreateSchema = z.object({
  title: z.string().trim().min(1).optional(),
})

export const chatMessageCreateSchema = z.object({
  sessionId: z.string().trim().min(1),
  message: z.string().trim().min(1).max(10_000),
  sources: z.array(z.unknown()).max(20).optional(),
  images: z.array(z.string().max(4096)).max(4).optional(),
})

export const noteCreateSchema = z.object({
  title: z.string().trim().min(1).max(255),
  content: z.string().trim().min(1).max(50_000),
})

export const noteUpdateSchema = z.object({
  title: z.string().trim().min(1).max(255).optional(),
  content: z.string().trim().min(1).max(50_000).optional(),
})
