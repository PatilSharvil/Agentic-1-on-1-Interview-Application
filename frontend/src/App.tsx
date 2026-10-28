import { useState } from 'react'
import Landing from './pages/Landing'
import Room from './pages/Room'
import GraphPage from './pages/GraphPage'

export default function App() {
  // Hooks always run; the knowledge-graph page is a standalone route.
  const [roomCode, setRoomCode] = useState<string | null>(null)
  const [name, setName] = useState<string>('Guest')

  if (window.location.pathname.startsWith('/graph/')) {
    return <GraphPage />
  }

  if (!roomCode) return <Landing onJoin={(code, n) => { setRoomCode(code); setName(n) }} />
  return <Room code={roomCode} name={name} onLeave={() => setRoomCode(null)} />
}
