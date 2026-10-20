import { useState } from 'react'
import Landing from './pages/Landing'
import Room from './pages/Room'
import GraphPage from './pages/GraphPage'

export default function App() {
  // Simple path-based routing for the knowledge graph page
  if (window.location.pathname.startsWith('/graph/')) {
    return <GraphPage />
  }

  const [roomCode, setRoomCode] = useState<string | null>(null)
  const [name, setName] = useState<string>('Guest')
  if (!roomCode) return <Landing onJoin={(code, n) => { setRoomCode(code); setName(n) }} />
  return <Room code={roomCode} name={name} onLeave={() => setRoomCode(null)} />
}