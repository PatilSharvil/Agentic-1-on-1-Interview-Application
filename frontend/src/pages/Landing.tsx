import { useState } from 'react'

export default function Landing({ onJoin }: { onJoin: (code: string, name: string) => void }) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [err, setErr] = useState('')

  async function createRoom() {
    const n = name.trim() || 'Host'
    const res = await fetch('/api/rooms', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ host_name: n }) })
    const data = await res.json()
    onJoin(data.code, n)
  }
  function joinRoom() {
    const c = code.trim().toUpperCase()
    const n = name.trim() || 'Guest'
    if (!c) { setErr('Enter a room code'); return }
    onJoin(c, n)
  }

  return (
    <div style={{ maxWidth: 420, margin: '80px auto', fontFamily: 'sans-serif' }}>
      <h1>Meeting Platform</h1>
      <input placeholder="Your name" value={name} onChange={e => setName(e.target.value)} style={{ width: '100%', padding: 8, marginBottom: 12 }} />
      <button onClick={createRoom} style={{ width: '100%', padding: 10, marginBottom: 24 }}>Create new meeting</button>
      <div>or join existing:</div>
      <input placeholder="Room code" value={code} onChange={e => setCode(e.target.value)} style={{ width: '100%', padding: 8, marginTop: 8 }} />
      <button onClick={joinRoom} style={{ width: '100%', padding: 10, marginTop: 8 }}>Join</button>
      {err && <p style={{ color: 'red' }}>{err}</p>}
    </div>
  )
}