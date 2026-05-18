export type RouteId =
  | 'dashboard'
  | 'chat'
  | 'notes'
  | 'encyclopedia'
  | 'system'

// TODO: parked for post-hackathon
// | 'journal'
// | 'entertainment'
// | 'gallery'
// | 'calculator'
// | 'settings'

export interface NavItem {
  id: RouteId
  label: string
  path: string
}

export const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: 'Status', path: '/' },
  { id: 'chat', label: 'AI Chat', path: '/chat' },
  { id: 'notes', label: 'Notepad', path: '/notes' },
  { id: 'encyclopedia', label: 'Encyclopedia', path: '/encyclopedia' },
  { id: 'system', label: 'System', path: '/system' },
]
