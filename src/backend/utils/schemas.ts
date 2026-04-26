import { z } from 'zod'

export const paginationSchema = z.object({
  limit: z.coerce.number().int().min(1).default(50),
  offset: z.coerce.number().int().min(0).default(0),
})

export const journalCreateSchema = z.object({
  content: z.string().trim().min(1),
  date: z.coerce.date().optional(),
})

export const journalUpdateSchema = z.object({
  content: z.string().trim().min(1).optional(),
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
