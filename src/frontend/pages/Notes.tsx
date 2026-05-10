import { useState, useEffect } from 'react'
import { PageHeader } from '../components/PageHeader'
import { fetchWithAuth } from '../utils/fetchWithAuth'

interface Note {
  id: string
  title: string
  content: string
  createdAt: string
  updatedAt: string
}

export function NotesPage() {
  const [notes, setNotes] = useState<Note[]>([])
  const [search, setSearch] = useState('')
  const [selectedNote, setSelectedNote] = useState<Note | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [loading, setLoading] = useState(false)

  const fetchNotes = async (q = '') => {
    try {
      const url = q ? `/api/notes?q=${encodeURIComponent(q)}` : '/api/notes'
      const res = await fetchWithAuth(url)
      if (res.ok) {
        const data = await res.json()
        setNotes(data.notes || [])
      }
    } catch (err) {
      console.error('Failed to fetch notes', err)
    }
  }

  useEffect(() => {
    fetchNotes(search)
  }, [search])

  const handleSave = async () => {
    if (!editTitle.trim() || !editContent.trim()) return
    setLoading(true)
    const url = selectedNote?.id ? `/api/notes/${selectedNote.id}` : '/api/notes'
    const method = selectedNote?.id ? 'PUT' : 'POST'
    
    try {
      const res = await fetchWithAuth(url, {
        method,
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ title: editTitle, content: editContent })
      })
      
      if (res.ok) {
        const data = await res.json()
        await fetchNotes(search)
        setSelectedNote(data.note)
        setIsEditing(false)
      }
    } catch (err) {
      console.error('Failed to save note', err)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this note?')) return
    try {
      const res = await fetchWithAuth(`/api/notes/${id}`, {
        method: 'DELETE'
      })
      if (res.ok) {
        if (selectedNote?.id === id) {
          setSelectedNote(null)
          setIsEditing(false)
        }
        await fetchNotes(search)
      }
    } catch (err) {
      console.error('Failed to delete note', err)
    }
  }

  const handleNewNote = () => {
    setSelectedNote(null)
    setEditTitle('')
    setEditContent('')
    setIsEditing(true)
  }

  const handleSelectNote = (note: Note) => {
    setSelectedNote(note)
    setEditTitle(note.title)
    setEditContent(note.content)
    setIsEditing(false)
  }

  return (
    <>
      <PageHeader title="Notepad" />
      <div style={{ display: 'flex', height: 'calc(100% - 60px)', gap: '1rem', marginTop: '1rem' }}>
        
        {/* Left Pane: List */}
        <div style={{ flex: '0 0 300px', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <input 
              type="text" 
              placeholder="SEARCH..." 
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ flex: 1, padding: '0.5rem', background: 'transparent', color: 'rgb(var(--main))', border: '1px solid rgba(var(--main), 0.3)', fontFamily: 'inherit' }}
            />
            <button className="btn" onClick={handleNewNote}>+ NEW</button>
          </div>
          
          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {notes.map(n => (
              <div 
                key={n.id} 
                onClick={() => handleSelectNote(n)}
                style={{ 
                  padding: '1rem', 
                  border: `1px solid ${selectedNote?.id === n.id ? 'rgb(var(--main))' : 'rgba(var(--main), 0.2)'}`,
                  cursor: 'pointer',
                  background: selectedNote?.id === n.id ? 'rgba(var(--alt), 0.1)' : 'transparent'
                }}
              >
                <div style={{ fontWeight: 'bold', marginBottom: '0.5rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{n.title}</div>
                <div style={{ fontSize: '0.8em', color: 'rgba(var(--main), 0.5)' }}>
                  {new Date(n.updatedAt).toLocaleDateString()}
                </div>
              </div>
            ))}
            {notes.length === 0 && <div className="text-dim" style={{ textAlign: 'center', marginTop: '2rem' }}>No notes found</div>}
          </div>
        </div>

        {/* Right Pane: Editor / View */}
        <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '1.5rem', gap: '1rem' }}>
          {isEditing ? (
            <>
              <input 
                type="text" 
                placeholder="NOTE TITLE" 
                value={editTitle}
                onChange={e => setEditTitle(e.target.value)}
                style={{ fontSize: '1.2em', padding: '0.5rem', background: 'transparent', color: 'rgb(var(--main))', border: '1px solid rgba(var(--main), 0.3)', fontFamily: 'inherit' }}
              />
              <textarea 
                placeholder="NOTE CONTENT..." 
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                style={{ flex: 1, padding: '0.5rem', background: 'transparent', color: 'rgb(var(--main))', border: '1px solid rgba(var(--main), 0.3)', fontFamily: 'inherit', resize: 'none' }}
              />
              <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                <button className="btn" onClick={() => setIsEditing(false)}>CANCEL</button>
                <button className="btn" disabled={loading} onClick={handleSave}>SAVE NOTE</button>
              </div>
            </>
          ) : selectedNote ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid rgba(var(--main), 0.2)', paddingBottom: '1rem' }}>
                <h2 style={{ fontSize: '1.5em', margin: 0 }}>{selectedNote.title}</h2>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button className="btn" onClick={() => setIsEditing(true)}>EDIT</button>
                  <button className="btn" onClick={() => handleDelete(selectedNote.id)}>DELETE</button>
                </div>
              </div>
              <div style={{ flex: 1, overflowY: 'auto', whiteSpace: 'pre-wrap', lineHeight: '1.6' }}>
                {selectedNote.content}
              </div>
              <div className="text-dim" style={{ fontSize: '0.8em', borderTop: '1px solid rgba(var(--main), 0.1)', paddingTop: '0.5rem' }}>
                Last updated: {new Date(selectedNote.updatedAt).toLocaleString()}
              </div>
            </>
          ) : (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }} className="placeholder">
              Select a note or create a new one
            </div>
          )}
        </div>
      </div>
    </>
  )
}
