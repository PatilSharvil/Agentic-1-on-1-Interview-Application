import { useEffect, useState } from 'react'

export default function Copilot({ code }: { code: string }) {
  const [questions, setQuestions] = useState<{ id: string; text: string; source: string }[]>([])
  const [uploading, setUploading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [nextLoading, setNextLoading] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [resumeName, setResumeName] = useState<string | null>(null)
  const [skills, setSkills] = useState<string[]>([])
  const [jobTitle, setJobTitle] = useState('')
  const [msg, setMsg] = useState('')
  const [graphCounts, setGraphCounts] = useState<{ nodes: number; edges: number } | null>(null)

  async function refreshGraphCounts() {
    try {
      const res = await fetch(`/api/rooms/${code}/graph`)
      if (!res.ok) return
      const g = await res.json()
      setGraphCounts({ nodes: (g.nodes || []).length, edges: (g.edges || []).length })
    } catch {}
  }

  useEffect(() => {
    fetch(`/api/rooms/${code}/questions`).then(r => (r.ok ? r.json() : [])).then(setQuestions).catch(() => {})
    fetch(`/api/rooms/${code}/resume`).then(async r => {
      if (!r.ok) return
      const data = await r.json()
      setResumeName(data.filename)
      setSkills(data.skills || [])
    }).catch(() => {})
    refreshGraphCounts()
  }, [code])

  async function uploadResume(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setMsg('Uploading and building the resume graph…')
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await fetch(`/api/rooms/${code}/resume`, { method: 'POST', body: fd })
      if (res.ok) {
        const data = await res.json()
        setResumeName(data.filename)
        setSkills(data.skills || [])
        setMsg(`Resume uploaded. Graph seeded with ${data.skills?.length || 0} skills.`)
        await refreshGraphCounts()
      } else {
        setMsg('Upload failed: ' + (await res.text()))
      }
    } catch (err) {
      setMsg('Upload failed: ' + String(err))
    }
    setUploading(false)
  }

  async function generateQuestions() {
    setGenerating(true)
    setMsg('Generating resume-specific questions…')
    try {
      const res = await fetch(`/api/rooms/${code}/questions/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_title: jobTitle || null, count: 5 }),
      })
      if (res.ok) {
        const data = await res.json()
        setQuestions(prev => [...prev, ...data])
        setMsg(`Generated ${data.length} questions.`)
      } else {
        setMsg('Generate failed: ' + (await res.text()))
      }
    } catch (err) {
      setMsg('Generate failed: ' + String(err))
    }
    setGenerating(false)
  }

  async function nextQuestion() {
    setNextLoading(true)
    setMsg('Reading the latest answer…')
    try {
      const res = await fetch(`/api/rooms/${code}/questions/next`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (res.ok) {
        const q = await res.json()
        setQuestions(prev => [...prev, q])
        setMsg('Adaptive follow-up added.')
      } else {
        setMsg('Next question failed: ' + (await res.text()))
      }
    } catch (err) {
      setMsg('Next question failed: ' + String(err))
    }
    setNextLoading(false)
    refreshGraphCounts()
  }

  async function rebuildGraph(source: 'all' | 'resume' = 'all') {
    setRebuilding(true)
    setMsg(source === 'resume' ? 'Rebuilding graph from resume…' : 'Rebuilding graph from resume + transcript…')
    try {
      const res = await fetch(`/api/rooms/${code}/graph/rebuild?source=${source}&force=true`, { method: 'POST' })
      if (res.ok) {
        const g = await res.json()
        setGraphCounts({ nodes: g.nodes.length, edges: g.edges.length })
        setMsg(`Graph rebuilt: ${g.nodes.length} nodes, ${g.edges.length} edges.`)
      } else {
        setMsg('Rebuild failed: ' + (await res.text()))
      }
    } catch (err) {
      setMsg('Rebuild failed: ' + String(err))
    }
    setRebuilding(false)
  }

  function copyGraphLink() {
    const url = `${window.location.origin}/graph/${code}`
    navigator.clipboard?.writeText(url)
    setMsg('Graph link copied: ' + url)
  }

  return (
    <div style={{ width: 340, borderLeft: '1px solid #333', padding: 12, background: '#111', color: '#eee', height: '100vh', overflow: 'auto', boxSizing: 'border-box' }}>
      <h3 style={{ marginTop: 0 }}>Copilot (Interviewer)</h3>

      <section style={{ marginBottom: 16 }}>
        <h4>1. Resume</h4>
        <input type="file" accept=".pdf,.docx,.txt,.md" onChange={uploadResume} disabled={uploading} />
        {uploading && <span> uploading…</span>}
        {resumeName && <div style={{ fontSize: 12, marginTop: 4 }}>Uploaded: {resumeName}</div>}
        {skills.length > 0 && (
          <div style={{ fontSize: 11, color: '#9ab', marginTop: 6, lineHeight: 1.5 }}>
            Detected: {skills.slice(0, 12).join(', ')}
          </div>
        )}
      </section>

      <section style={{ marginBottom: 16 }}>
        <h4>2. Questions</h4>
        <input placeholder="Job title (optional)" value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} style={{ width: '100%', marginBottom: 6, boxSizing: 'border-box' }} />
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button onClick={generateQuestions} disabled={generating}>{generating ? 'Generating…' : 'Generate questions'}</button>
          <button onClick={nextQuestion} disabled={nextLoading}>{nextLoading ? 'Thinking…' : 'Get next question'}</button>
        </div>
        <ol style={{ paddingLeft: 18, marginTop: 8 }}>
          {questions.map((q) => (
            <li key={q.id} style={{ marginBottom: 6, fontSize: 13 }}>
              {q.text} <span style={{ color: '#888', fontSize: 10 }}>({q.source})</span>
            </li>
          ))}
        </ol>
      </section>

      <section style={{ marginBottom: 16 }}>
        <h4>3. Knowledge Graph</h4>
        <div style={{ fontSize: 12, color: '#9ab', marginBottom: 6 }}>
          {graphCounts ? `${graphCounts.nodes} nodes · ${graphCounts.edges} edges` : 'no graph yet'}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button onClick={() => rebuildGraph('all')} disabled={rebuilding}>{rebuilding ? 'Rebuilding…' : 'Rebuild (resume + transcript)'}</button>
          <button onClick={() => rebuildGraph('resume')} disabled={rebuilding}>Resume only</button>
        </div>
        <div style={{ marginTop: 8, display: 'flex', gap: 10 }}>
          <a href={`/graph/${code}`} target="_blank" rel="noreferrer" style={{ color: '#4af' }}>Open live graph</a>
          <button onClick={copyGraphLink} style={{ fontSize: 11 }}>Copy link</button>
        </div>
        <div style={{ fontSize: 11, color: '#777', marginTop: 6 }}>
          Auto-updates ~5s after each candidate answer.
        </div>
      </section>

      {msg && <div style={{ fontSize: 12, color: '#ccc', borderTop: '1px solid #333', paddingTop: 8 }}>{msg}</div>}
    </div>
  )
}
