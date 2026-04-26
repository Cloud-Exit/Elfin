import { paginationSchema } from './schemas.js'

export function parsePagination(url: URL) {
  const params = Object.fromEntries(url.searchParams.entries())
  const result = paginationSchema.safeParse(params)
  if (!result.success) {
    const issue = result.error.issues[0]
    if (issue) {
      throw new Error(`${String(issue.path[0])}: ${issue.message}`)
    }
    throw new Error(result.error.message)
  }
  return { limit: Math.min(result.data.limit, 200), offset: result.data.offset }
}
