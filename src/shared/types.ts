export type RouteId =
  | 'dashboard'
  | 'chat'
  | 'journal'
  | 'notes'
  | 'encyclopedia'
  | 'entertainment'
  | 'gallery'
  | 'calculator'
  | 'settings'

export interface NavItem {
  id: RouteId
  label: string
  path: string
}

export const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: 'Status', path: '/' },
  { id: 'chat', label: 'AI Chat', path: '/chat' },
  { id: 'journal', label: 'Journal', path: '/journal' },
  { id: 'notes', label: 'Notepad', path: '/notes' },
  { id: 'encyclopedia', label: 'Encyclopedia', path: '/encyclopedia' },
  { id: 'entertainment', label: 'Entertainment', path: '/entertainment' },
  { id: 'gallery', label: 'Gallery', path: '/gallery' },
  { id: 'calculator', label: 'Calculator', path: '/calculator' },
  { id: 'settings', label: 'Settings', path: '/settings' },
]
