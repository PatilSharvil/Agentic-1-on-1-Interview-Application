import { useEffect, useState } from 'react'
import { IconUpload, IconSpark, IconGraph, IconExternal } from './icons'

export default function Copilot({ code }: { code: string }) {
  const [questions, setQuestions] = useState<{ id: string; text: string; source: string }[]>([])
  const [uploading, setUploading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [nextLoading, setNextLoading] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [resumeName, setResumeName] = useState<string | null>(null)
  const [skills, setSkills] = useState<string[]>([])
  const [jobTitle, setJobTitle] = useState('')
  const [msg, setMsg] = useState<{ tone: 'busy' | 'ok' | 'error'; text: string } | null>(null)
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
    setMsg({ tone: 'busy', text: 'Uploading and building the resume graph…' })
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await fetch(`/api/rooms/${code}/resume`, { method: 'POST', body: fd })
      if (res.ok) {
        const data = await res.json()
        setResumeName(data.filename)
        setSkills(data.skills || [])
        setMsg({ tone: 'ok', text: `Resume seeded the graph with ${data.skills?.length || 0} skills.` })
        await refreshGraphCounts()
      } else {
        setMsg({ tone: 'error', text: 'Upload failed — ' + (await res.text()) })
      }
    } catch (err) {
      setMsg({ tone: 'error', text: 'Upload failed — ' + String(err) })
    }
    setUploading(false)
  }

  async function generateQuestions() {
    setGenerating(true)
    setMsg({ tone: 'busy', text: 'Generating resume-specific questions…' })
    try {
      const res = await fetch(`/api/rooms/${code}/questions/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_title: jobTitle || null, count: 5 }),
      })
      if (res.ok) {
        const data = await res.json()
        setQuestions(prev => [...prev, ...data])
        setMsg({ tone: 'ok', text: `${data.length} questions added.` })
      } else {
        setMsg({ tone: 'error', text: 'Generate failed — ' + (await res.text()) })
      }
    } catch (err) {
      setMsg({ tone: 'error', text: 'Generate failed — ' + String(err) })
    }
    setGenerating(false)
  }

  async function nextQuestion() {
    setNextLoading(true)
    setMsg({ tone: 'busy', text: 'Reading the latest answer…' })
    try {
      const res = await fetch(`/api/rooms/${code}/questions/next`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (res.ok) {
        const q = await res.json()
        setQuestions(prev => [...prev, q])
        setMsg({ tone: 'ok', text: 'Adaptive follow-up added.' })
      } else {
        setMsg({ tone: 'error', text: 'Next question failed — ' + (await res.text()) })
      }
    } catch (err) {
      setMsg({ tone: 'error', text: 'Next question failed — ' + String(err) })
    }
    setNextLoading(false)
    refreshGraphCounts()
  }

  async function rebuildGraph(source: 'all' | 'resume' = 'all') {
    setRebuilding(true)
    setMsg({ tone: 'busy', text: source === 'resume' ? 'Rebuilding from the resume…' : 'Rebuilding from resume + transcript…' })
    try {
      const res = await fetch(`/api/rooms/${code}/graph/rebuild?source=${source}&force=true`, { method: 'POST' })
      if (res.ok) {
        const g = await res.json()
        setGraphCounts({ nodes: g.nodes.length, edges: g.edges.length })
        setMsg({ tone: 'ok', text: `Graph rebuilt: ${g.nodes.length} nodes · ${g.edges.length} edges.` })
      } else {
        setMsg({ tone: 'error', text: 'Rebuild failed — ' + (await res.text()) })
      }
    } catch (err) {
      setMsg({ tone: 'error', text: 'Rebuild failed — ' + String(err) })
    }
    setRebuilding(false)
  }

  function copyGraphLink() {
    const url = `${window.location.origin}/graph/${code}`
    void navigator.clipboard?.writeText(url)
    setMsg({ tone: 'ok', text: 'Graph link copied — paste it to share the live view.' })
  }

  return (
    <div className="copilot scroll-pane">
      {/* 01 · resume */}
      <section className="step">
        <div className="step-head">
          <span className="step-num">01</span>
          <h3 className="step-title">Resume</h3>
          <IconUpload size={16} />
        </div>
        <div className="step-body">
          <label className={`upload-label${uploading ? ' is-busy' : ''}`}>
            <IconUpload size={16} />
            {uploading ? 'Building the graph…' : 'Upload resume — PDF · DOCX · TXT · MD'}
            <input type="file" accept=".pdf,.docx,.txt,.md" onChange={uploadResume} disabled={uploading} />
          </label>
          {resumeName && (
            <div className="resume-meta">
              <div className="resume-name">{resumeName}</div>
              {skills.length > 0 && (
                <div className="skill-tags">
                  {skills.slice(0, 12).map((s) => <span key={s}>{s}</span>)}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* 02 · questions */}
      <section className="step">
        <div className="step-head">
          <span className="step-num">02</span>
          <h3 className="step-title">Questions</h3>
          <IconSpark size={16} />
        </div>
        <div className="step-body">
          <input
            className="input"
            placeholder="Job title (optional)"
            value={jobTitle}
            onChange={(e) => setJobTitle(e.target.value)}
            aria-label="Job title"
          />
          <div className="btn-row">
            <button className="btn btn-primary btn-sm" onClick={() => void generateQuestions()} disabled={generating}>
              {generating ? 'Generating…' : 'Generate 5'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => void nextQuestion()} disabled={nextLoading}>
              {nextLoading ? 'Thinking…' : 'Next from answer'}
            </button>
          </div>
          {questions.length > 0 && (
            <ol className="q-list">
              {questions.map((q) => (
                <li key={q.id}>
                  <span className="q-mark" aria-hidden="true">→</span>
                  {q.text}
                  <span className="q-src">{q.source}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </section>

      {/* 03 · knowledge graph */}
      <section className="step">
        <div className="step-head">
          <span className="step-num">03</span>
          <h3 className="step-title">Knowledge graph</h3>
          <IconGraph size={16} />
        </div>
        <div className="step-body">
          <div className="graph-meta">
            <span className="graph-counts">
              {graphCounts ? `${graphCounts.nodes} nodes · ${graphCounts.edges} edges` : 'no graph yet'}
            </span>
          </div>
          <div className="btn-row">
            <button className="btn btn-ghost btn-sm" onClick={() => void rebuildGraph('all')} disabled={rebuilding}>
              {rebuilding ? 'Rebuilding…' : 'Rebuild all'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => void rebuildGraph('resume')} disabled={rebuilding}>
              Resume only
            </button>
          </div>
          <div className="btn-row">
            <a className="btn btn-ghost btn-sm" href={`/graph/${code}`} target="_blank" rel="noreferrer">
              Open live graph <IconExternal />
            </a>
            <button className="btn btn-ghost btn-sm" onClick={copyGraphLink}>Copy link</button>
          </div>
          <p className="step-note">Auto-updates ~5s after each candidate answer.</p>
        </div>
      </section>

      {msg && (
        <div
          className={`copilot-msg${msg.tone === 'error' ? ' is-error' : msg.tone === 'ok' ? ' is-ok' : ''}`}
          role="status"
        >
          {msg.text}
        </div>
      )}
    </div>
  )
}
