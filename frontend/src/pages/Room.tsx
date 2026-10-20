import { useState, useRef, useEffect } from 'react'
import Copilot from '../components/Copilot'

const WORKLET_CODE = `class RecorderProcessor extends AudioWorkletProcessor {
  constructor() { super(); this.buf = []; this.port.onmessage = (e) => { if (e.data === 'flush') { this.port.postMessage({ type: 'data', chunks: this.buf }); this.buf = []; } }; }
  process(inputs) { const input = inputs[0]; if (input && input[0]) this.buf.push(new Float32Array(input[0])); return true; }
}
registerProcessor('recorder-processor', RecorderProcessor);`

const ICE_SERVERS = [{ urls: 'stun:stun.l.google.com:19302' }]

function encodeWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const numChannels = 1, bitsPerSample = 16, bytesPerSample = 2
  const blockAlign = numChannels * bytesPerSample
  const byteRate = sampleRate * blockAlign
  const dataSize = samples.length * bytesPerSample
  const buffer = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buffer)
  const ws = (off: number, s: string) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)) }
  ws(0, 'RIFF'); view.setUint32(4, 36 + dataSize, true); ws(8, 'WAVE')
  ws(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true)
  view.setUint16(22, numChannels, true); view.setUint32(24, sampleRate, true)
  view.setUint32(28, byteRate, true); view.setUint16(32, blockAlign, true); view.setUint16(34, bitsPerSample, true)
  ws(36, 'data'); view.setUint32(40, dataSize, true)
  let off = 44
  for (let i = 0; i < samples.length; i++) {
    let s = Math.max(-1, Math.min(1, samples[i]))
    s = s < 0 ? s * 0x8000 : s * 0x7fff
    view.setInt16(off, s, true); off += 2
  }
  return buffer
}

function float32Concat(chunks: Float32Array[]): Float32Array {
  let len = 0
  for (const c of chunks) len += c.length
  const out = new Float32Array(len)
  let off = 0
  for (const c of chunks) { out.set(c, off); off += c.length }
  return out
}

export default function Room({ code, name, onLeave }: { code: string; name: string; onLeave: () => void }) {
  const localVideo = useRef<HTMLVideoElement>(null)
  const remoteVideo = useRef<HTMLVideoElement>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const localStream = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const chunksRef = useRef<Float32Array[]>([])
  // (sample rate is fixed at 16000 in AudioContext)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [status, setStatus] = useState('connecting...')
  const [chat, setChat] = useState<{ sender: string; body: string }[]>([])
  const [msg, setMsg] = useState('')
  const [transcripts, setTranscripts] = useState<{ speaker: string; text: string }[]>([])
  const [muted, setMuted] = useState(false)
  const [camOff, setCamOff] = useState(false)
  const [webSpeechOn, setWebSpeechOn] = useState(false)
  const [recording, setRecording] = useState(false)
  const [role, setRole] = useState<string>('guest')

  async function startAudioCapture() {
    if (audioCtxRef.current) { console.log('audio capture already running'); return }
    const stream = localStream.current
    if (!stream || stream.getAudioTracks().length === 0) { console.error('no audio track'); return }
    const ctx = new AudioContext({ sampleRate: 16000 })
    const source = ctx.createMediaStreamSource(stream)
    const blob = new Blob([WORKLET_CODE], { type: 'application/javascript' })
    const url = URL.createObjectURL(blob)
    await ctx.audioWorklet.addModule(url)
    URL.revokeObjectURL(url)
    const node = new AudioWorkletNode(ctx, 'recorder-processor')
    node.port.onmessage = (e) => {
      if (e.data?.type === 'data' && Array.isArray(e.data.chunks)) {
        for (const c of e.data.chunks) chunksRef.current.push(new Float32Array(c))
      }
    }
    source.connect(node)
    audioCtxRef.current = ctx
    workletNodeRef.current = node
    console.log('audio capture started, sampleRate', ctx.sampleRate)
  }

  function stopAudioCapture() {
    workletNodeRef.current?.disconnect()
    workletNodeRef.current = null
    audioCtxRef.current?.close()
    audioCtxRef.current = null
    chunksRef.current = []
  }

  async function flushAudio() {
    const node = workletNodeRef.current
    if (!node) { console.error('no worklet node'); return }
    if (wsRef.current?.readyState !== WebSocket.OPEN) { console.warn('ws not open, skipping flush'); chunksRef.current = []; return }
    node.port.postMessage('flush')
    await new Promise((r) => setTimeout(r, 100))
    const samples = float32Concat(chunksRef.current)
    chunksRef.current = []
    if (samples.length < 1600) { console.log('too few samples:', samples.length); return }
    let maxAmp = 0
    for (let i = 0; i < samples.length; i++) maxAmp = Math.max(maxAmp, Math.abs(samples[i]))
    console.log('audio max amplitude:', maxAmp.toFixed(4))
    if (maxAmp < 0.01) { console.log('silence, skipping'); chunksRef.current = []; return }
    const wav = encodeWav(samples, audioCtxRef.current?.sampleRate || 16000)
    const buf = new Uint8Array(wav)
    let bin = ''
    for (let i = 0; i < buf.length; i += 0x8000) {
      bin += String.fromCharCode.apply(null, Array.from(buf.subarray(i, i + 0x8000)))
    }
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'audio-chunk', audio: btoa(bin), suffix: '.wav', speaker: role === 'host' ? 'Interviewer' : 'Candidate' }))
      console.log('sent wav chunk, samples:', samples.length, 'bytes:', wav.byteLength)
    } else {
      console.warn('ws closed before send')
    }
  }

  // Start/stop recording controls audio capture + 5s chunk interval
  useEffect(() => {
    if (recording) {
      startAudioCapture().then(() => {
        if (intervalRef.current) clearInterval(intervalRef.current)
        intervalRef.current = setInterval(() => { flushAudio() }, 5000)
      })
    } else {
      if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
      stopAudioCapture()
    }
    return () => {
      if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
    }
  }, [recording])

  useEffect(() => {
    let cancelled = false
    async function start() {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      if (cancelled) return
      localStream.current = stream
      if (localVideo.current) localVideo.current.srcObject = stream

      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS })
      pcRef.current = pc
      stream.getTracks().forEach(t => pc.addTrack(t, stream))
      pc.ontrack = (e) => { if (remoteVideo.current) remoteVideo.current.srcObject = e.streams[0] }
      pc.onicecandidate = (e) => {
        if (e.candidate && wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'ice-candidate', candidate: e.candidate }))
        }
      }

      const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${wsProto}//${location.host}/ws/${code}?name=${encodeURIComponent(name)}`)
      wsRef.current = ws
      ws.onopen = () => setStatus('connected')
      ws.onmessage = async (ev) => {
        const data = JSON.parse(ev.data)
        switch (data.type) {
          case 'joined':
            if (data.role) setRole(data.role)
            break
          case 'start-recording':
            setRecording(true)
            break
          case 'stop-recording':
            setRecording(false)
            break
          case 'join':
            if (pc.signalingState === 'stable') {
              const offer = await pc.createOffer()
              await pc.setLocalDescription(offer)
              ws.send(JSON.stringify({ type: 'offer', sdp: pc.localDescription }))
            }
            break
          case 'offer':
            await pc.setRemoteDescription(new RTCSessionDescription(data.sdp))
            const answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            ws.send(JSON.stringify({ type: 'answer', sdp: pc.localDescription }))
            break
          case 'answer':
            await pc.setRemoteDescription(new RTCSessionDescription(data.sdp))
            break
          case 'ice-candidate':
            try { await pc.addIceCandidate(data.candidate) } catch {}
            break
          case 'chat':
            setChat(c => [...c, { sender: data.sender, body: data.body }])
            break
          case 'transcript':
            setTranscripts(t => [...t, { speaker: data.speaker, text: data.text }])
            break
          case 'leave':
            setStatus('peer left')
            break
        }
      }
      ws.onclose = () => setStatus('disconnected')
    }
    start()
    return () => {
      cancelled = true
      if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
      stopAudioCapture()
      pcRef.current?.close()
      wsRef.current?.close()
      localStream.current?.getTracks().forEach(t => t.stop())
    }
  }, [code, name])

  // Web Speech API: free, real-time, browser-native STT (fallback)
  useEffect(() => {
    if (!webSpeechOn) return
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) { console.error('SpeechRecognition not supported'); setWebSpeechOn(false); return }
    const rec = new SR()
    rec.continuous = true
    rec.interimResults = false
    rec.lang = 'en-US'
    rec.onresult = (e: any) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) {
          const text = e.results[i][0].transcript.trim()
          if (text && wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'transcript', speaker: role === 'host' ? 'Interviewer' : 'Candidate', text }))
          }
        }
      }
    }
    rec.onerror = (e: any) => console.error('SpeechRecognition error:', e.error)
    rec.onend = () => { if (webSpeechOn) try { rec.start() } catch {} }
    try { rec.start() } catch (e) { console.error('SpeechRecognition start failed:', e) }
    return () => { try { rec.stop() } catch {} }
  }, [webSpeechOn, name])

  function toggleMute() {
    localStream.current?.getAudioTracks().forEach(t => (t.enabled = muted))
    setMuted(!muted)
  }
  function toggleCam() {
    localStream.current?.getVideoTracks().forEach(t => (t.enabled = camOff))
    setCamOff(!camOff)
  }
  function toggleWebSpeech() {
    setWebSpeechOn((v) => !v)
  }
  function sendChat() {
    if (!msg.trim()) return
    wsRef.current?.send(JSON.stringify({ type: 'chat', body: msg }))
    setMsg('')
  }
  async function shareScreen() {
    try {
      const disp = await navigator.mediaDevices.getDisplayMedia({ video: true })
      const track = disp.getVideoTracks()[0]
      const sender = pcRef.current?.getSenders().find(s => s.track?.kind === 'video')
      sender?.replaceTrack(track)
      track.onended = () => {
        const cam = localStream.current?.getVideoTracks()[0]
        if (cam) sender?.replaceTrack(cam)
      }
    } catch {}
  }
  async function testSttWav() {
    try {
      const res = await fetch('/test.wav')
      const buf = new Uint8Array(await res.arrayBuffer())
      let bin = ''
      for (let i = 0; i < buf.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, Array.from(buf.subarray(i, i + 0x8000)))
      }
      wsRef.current?.send(JSON.stringify({ type: 'audio-chunk', audio: btoa(bin), suffix: '.wav', speaker: role === 'host' ? 'Interviewer' : 'Candidate' }))
      console.log('test wav sent', buf.length)
    } catch (e) { console.error('test wav failed', e) }
  }

  return (
    <div style={{ display: 'flex', fontFamily: 'sans-serif' }}>
      <div style={{ flex: 1, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <h2>Room {code} — {name}</h2>
        <button onClick={onLeave}>Leave</button>
      </div>
      <div style={{ color: '#666', marginBottom: 8 }}>{status}</div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <video ref={localVideo} autoPlay muted playsInline style={{ width: 320, background: '#000' }} />
        <video ref={remoteVideo} autoPlay playsInline style={{ width: 320, background: '#000' }} />
      </div>
      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button onClick={toggleMute}>{muted ? 'Unmute' : 'Mute'}</button>
        <button onClick={toggleCam}>{camOff ? 'Cam on' : 'Cam off'}</button>
        <button onClick={shareScreen}>Share screen</button>
        {role === 'host' && (
          <>
            <button onClick={() => {
              const next = !recording
              setRecording(next)
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: next ? 'start-recording' : 'stop-recording' }))
              }
            }}>{recording ? 'Stop recording' : 'Start recording'}</button>
            <button onClick={flushAudio}>Send audio now</button>
            <button onClick={testSttWav}>Test STT (wav)</button>
            <button onClick={toggleWebSpeech}>{webSpeechOn ? 'Stop browser STT' : 'Start browser STT'}</button>
          </>
        )}
      </div>
      <div style={{ display: 'flex', gap: 16, marginTop: 16 }}>
        <div style={{ flex: 1 }}>
          <h3>Chat</h3>
          <div style={{ height: 160, overflow: 'auto', border: '1px solid #ccc', padding: 8 }}>
            {chat.map((c, i) => <div key={i}><b>{c.sender}:</b> {c.body}</div>)}
          </div>
          <div style={{ display: 'flex', marginTop: 4 }}>
            <input value={msg} onChange={e => setMsg(e.target.value)} onKeyDown={e => e.key === 'Enter' && sendChat()} style={{ flex: 1 }} />
            <button onClick={sendChat}>Send</button>
          </div>
        </div>
        <div style={{ flex: 1 }}>
          <h3>Transcript (STT)</h3>
          <div style={{ height: 160, overflow: 'auto', border: '1px solid #ccc', padding: 8 }}>
            {transcripts.map((t, i) => <div key={i}><b>{t.speaker}:</b> {t.text}</div>)}
          </div>
        </div>
      </div>
      </div>
      {role === 'host' && <Copilot code={code} />}
    </div>
  )
}