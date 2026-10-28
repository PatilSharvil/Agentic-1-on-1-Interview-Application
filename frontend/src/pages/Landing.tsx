import { useRef, useState } from 'react'

export default function Landing({ onJoin }: { onJoin: (code: string, name: string) => void }) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const joinRef = useRef<HTMLInputElement>(null)

  async function createRoom() {
    if (busy) return
    const n = name.trim() || 'Host'
    setErr('')
    setBusy(true)
    try {
      const res = await fetch('/api/rooms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host_name: n }),
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      onJoin(data.code, n)
    } catch {
      setErr('Could not open a room — the server may be offline. Try again.')
      setBusy(false)
    }
  }

  function joinRoom() {
    const c = code.trim().toUpperCase()
    const n = name.trim() || 'Guest'
    if (!c) { setErr('Enter the room code your interviewer shared.'); return }
    setErr('')
    onJoin(c, n)
  }

  const codeReady = code.trim().length > 0

  return (
    <div className="landing">
      <header className="land-top rise">
        <div className="brand">
          <span className="eq"><i /><i /><i /><i /><i /></span>
          Interview Room
        </div>
        <span className="chip land-top-note">WEBRTC · LIVE STT · KNOWLEDGE GRAPH</span>
      </header>

      <main className="land-hero">
        <div className="land-copy">
          <p className="eyebrow rise d1">One-to-one · AI in the loop</p>
          <h1 className="h-display rise d1">
            The interview that <em>remembers</em> every answer.
          </h1>
          <p className="land-sub rise d2">
            Video interviews with live captions, adaptive follow-up questions, and a
            knowledge graph built from the resume and the conversation while you talk.
          </p>
          <ul className="land-feats rise d3">
            <li className="chip">LIVE CAPTIONS</li>
            <li className="chip">ADAPTIVE QUESTIONS</li>
            <li className="chip">SKILL GRAPH</li>
          </ul>
        </div>

        <section className="land-card rise d2" aria-label="Start or join an interview">
          <div className="card-tag">
            <span className="eyebrow">Ready when you are</span>
            <span className="eq still" aria-hidden="true"><i /><i /><i /><i /><i /></span>
          </div>

          <div className="land-form">
            <div className="field">
              <label htmlFor="name" className="eyebrow" style={{ letterSpacing: '0.22em' }}>Your name</label>
              <input
                id="name"
                className="input"
                placeholder="e.g. Priya"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void createRoom()}
                autoComplete="name"
              />
            </div>

            <button className="btn btn-primary btn-block" onClick={() => void createRoom()} disabled={busy}>
              {busy ? 'Opening room…' : 'Start an interview'}
            </button>

            <div className="land-divider" role="separator">or join</div>

            <div className="field">
              <label htmlFor="code" className="eyebrow" style={{ letterSpacing: '0.22em' }}>Room code</label>
              <span className="vf">
                <i className="vf-c tl" /><i className="vf-c tr" /><i className="vf-c bl" /><i className="vf-c br" />
                <input
                  id="code"
                  ref={joinRef}
                  className="input input-mono"
                  placeholder="e.g. K7X2MN9P"
                  value={code}
                  onChange={(e) => setCode(e.target.value.toUpperCase())}
                  onKeyDown={(e) => e.key === 'Enter' && joinRoom()}
                  spellCheck={false}
                  autoComplete="off"
                />
              </span>
            </div>

            <button className="btn btn-ghost btn-block" onClick={joinRoom} disabled={!codeReady}>
              Join with code
            </button>

            {err && (
              <p className="land-err" role="alert">
                <span aria-hidden="true">▲</span> {err}
              </p>
            )}
          </div>
        </section>
      </main>

      <footer className="land-foot rise d3">
        <span>PEER-TO-PEER VIDEO · GOOGLE STUN</span>
        <span>NO ACCOUNTS · SHARE A CODE AND GO</span>
      </footer>
    </div>
  )
}
