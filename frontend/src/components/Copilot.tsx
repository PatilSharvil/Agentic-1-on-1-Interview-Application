import { useState } from 'react'

export default function Copilot({ code }: { code: string }) {
  const [questions, setQuestions] = useState<{ id: string; text: string; source: string }[]>([])
  const [uploading, setUploading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [nextLoading, setNextLoading] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [resumeName, setResumeName] = useState<string | null>(null)
  const [jobTitle, setJobTitle] = useState('')
  const [msg, setMsg] = useState('')

  async function uploadResume(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setMsg('')
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`/api/rooms/${code}/resume`, { method: 'POST', body: fd })
    if (res.ok) {
      const data = await res.json()
      setResumeName(data.filename)
      setMsg('Resume uploaded.')
    } else {
      setMsg('Upload failed: ' + (await res.text()))
    }
    setUploading(false)
  }

  async function generateQuestions() {
    setGenerating(true)
    setMsg('')
    const res = await fetch(`/api/rooms/${code}/questions/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_title: jobTitle || null, count: 5 }),
    })
    if (res.ok) {
      const data = await res.json()
      setQuestions(data)
      setMsg(`Generated ${data.length} questions.`)
    } else {
      setMsg('Generate failed: ' + (await res.text()))
    }
    setGenerating(false)
  }

  async function nextQuestion() {
    setNextLoading(true)
    setMsg('')
    const res = await fetch(`/api/rooms/${code}/questions/next`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    if (res.ok) {
      const q = await res.json()
      setQuestions((prev) => [...prev, q])
      setMsg('Next question added.')
    } else {
      setMsg('Next question failed: ' + (await res.text()))
    }
    setNextLoading(false)
  }

  async function rebuildGraph() {
    setRebuilding(true)
    setMsg('')
    const res = await fetch(`/api/rooms/${code}/graph/rebuild`, { method: 'POST' })
    if (res.ok) {
      setMsg('Knowledge graph rebuilt.')
    } else {
      setMsg('Rebuild failed: ' + (await res.text()))
    }
    setRebuilding(false)
  }

  return (
    <div style={{ width: 320, borderLeft: '1px solid #333', padding: 12, background: '#111', color: '#eee', height: '100vh', overflow: 'auto', boxSizing: 'border-box' }}>
      <h3 style={{ marginTop: 0 }}>Copilot (Interviewer)</h3>

      <section style={{ marginBottom: 16 }}>
        <h4>Resume</h4>
        <input type="file" accept=".pdf,.txt,.md" onChange={uploadResume} disabled={uploading} />
        {uploading && <span> uploading...</span>}
        {resumeName && <div style={{ fontSize: 12, marginTop: 4 }}>Uploaded: {resumeName}</div>}
      </section>

      <section style={{ marginBottom: 16 }}>
        <h4>Questions</h4>
        <input placeholder="Job title (optional)" value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} style={{ width: '100%', marginBottom: 6 }} />
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button onClick={generateQuestions} disabled={generating}>Generate questions</button>
          <button onClick={nextQuestion} disabled={nextLoading}>Get next question</button>
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
        <h4>Knowledge Graph</h4>
        <button onClick={rebuildGraph} disabled={rebuilding}>Rebuild graph</button>
        <div style={{ marginTop: 6 }}>
          <a href={`/graph/${code}`} target="_blank" rel="noreferrer" style={{ color: '#4af' }}>
            Open live graph
          </a>
        </div>
      </section>

      {msg && <div style={{ fontSize: 12, color: '#aaa' }}>{msg}</div>}
    </div>
  )
}