import { createBrowserRouter } from 'react-router'
import { Shell } from './components/Shell'
import { DashboardPage } from './pages/Dashboard'
import { ChatPage } from './pages/Chat'
import { NotesPage } from './pages/Notes'
import { EncyclopediaPage } from './pages/Encyclopedia'
import { SystemPage } from './pages/System'

// TODO: parked for post-hackathon
// import { JournalPage } from './pages/Journal'
// import { EntertainmentPage } from './pages/Entertainment'
// import { GalleryPage } from './pages/Gallery'
// import { CalculatorPage } from './pages/Calculator'
// import { SettingsPage } from './pages/Settings'

export const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'chat', element: <ChatPage /> },
      { path: 'notes', element: <NotesPage /> },
      { path: 'encyclopedia', element: <EncyclopediaPage /> },
      { path: 'system', element: <SystemPage /> },
    ],
  },
])
