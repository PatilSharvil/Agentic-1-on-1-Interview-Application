import { useState, useRef, useEffect } from 'react'
import Copilot from '../components/Copilot'
import {
  IconMic, IconMicOff, IconCam, IconCamOff, IconScreen, IconRecord, IconStop,
  IconLeave, IconSend, IconWave,
} from '../components/icons'

const WORKLET_CODE = `
class RecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.sr = sampleRate
    this.frameMs = (128 / sampleRate) * 1000
    this.preRollMax = Math.max(8, Math.round(0.28 * sampleRate / 128))
    this.preRoll = []
    this.buf = []
    this.inSpeech = false
    this.silenceMs = 0
    this.speechMs = 0
    this.noise = 0.0025
    // Endpointing: how much silence ends an utterance, and the hard cap that
    // keeps a continuous monologue flowing. The server can retune both at
    // runtime via a {type:'config'} message (see the WS join snapshot).
    this.endpointSilenceMs = 1200
    this.maxChunkMs = 15000
    this.port.onmessage = (e) => {
      if (e.data === 'flush') this.emit(true)
      else if (e.data && e.data.type === 'config') {
        if (typeof e.data.endpointSilenceMs === 'number' && e.data.endpointSilenceMs >= 200) {
          this.endpointSilenceMs = e.data.endpointSilenceMs
        }
        if (typeof e.data.maxChunkMs === 'number' && e.data.maxChunkMs >= 3000) {
          this.maxChunkMs = e.data.maxChunkMs
        }
      }
    }
  }
  rms(frame) {
    let sum = 0
    for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i]
    return Math.sqrt(sum / frame.length)
  }
  process(inputs) {
    const input = inputs[0]
    const ch = input && input[0]
    if (!ch) return true
    const frame = new Float32Array(ch)
    const rms = this.rms(frame)
    if (!this.inSpeech) {
      // Track the room's noise floor slowly, and only while nobody is talking.
      this.noise = this.noise * 0.97 + Math.min(rms, this.noise * 3) * 0.03
    }
    const threshold = Math.max(0.007, this.noise * 2.9)
    const voiced = rms > threshold

    if (voiced) {
      if (!this.inSpeech) {
        this.inSpeech = true
        this.buf = this.preRoll.slice()
        this.preRoll = []
        this.speechMs = 0
      }
      this.silenceMs = 0
      this.speechMs += this.frameMs
      this.buf.push(frame)
      // The cap must also fire while voiced: a speaker who never pauses would
      // otherwise buffer forever and their transcript would never appear.
      if (this.buf.length * this.frameMs >= this.maxChunkMs) this.emit(false)
    } else if (this.inSpeech) {
      this.buf.push(frame)
      this.silenceMs += this.frameMs
      // End the utterance only on a real pause, so words are never cut in half.
      if ((this.silenceMs >= this.endpointSilenceMs && this.speechMs >= 320) || this.buf.length * this.frameMs >= this.maxChunkMs) {
        this.emit(false)
      }
    } else {
      this.preRoll.push(frame)
      if (this.preRoll.length > this.preRollMax) this.preRoll.shift()
    }
    return true
  }
  emit(force) {
    if (!this.buf.length) return
    const chunks = this.buf
    const speechMs = this.speechMs
    this.buf = []
    // Stale pre-roll would duplicate audio into the next chunk after a
    // max-length cut mid-speech (pre-roll only refreshes during silence).
    this.preRoll = []
    this.inSpeech = false
    this.silenceMs = 0
    this.speechMs = 0
    if (speechMs < 280 && !force) return
    this.port.postMessage({ type: 'chunk', chunks, sampleRate: this.sr, speechMs })
  }
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

async function resampleTo16k(samples: Float32Array, fromRate: number): Promise<Float32Array> {
  if (fromRate === 16000) return samples
  const length = Math.max(1, Math.round(samples.length * 16000 / fromRate))
  try {
    const off = new OfflineAudioContext(1, length, 16000)
    const buffer = off.createBuffer(1, samples.length, fromRate)
    buffer.getChannelData(0).set(samples)
    const src = off.createBufferSource()
    src.buffer = buffer
    src.connect(off.destination)
    src.start()
    const rendered = await off.startRendering()
    return rendered.getChannelData(0)
  } catch {
    // Fallback: linear interpolation
    const ratio = fromRate / 16000
    const out = new Float32Array(length)
    for (let i = 0; i < length; i++) {
      const pos = i * ratio
      const i0 = Math.floor(pos)
      const i1 = Math.min(i0 + 1, samples.length - 1)
      const frac = pos - i0
      out[i] = samples[i0] * (1 - frac) + samples[i1] * frac
    }
    return out
  }
}

function b64FromBytes(bytes: Uint8Array): string {
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)))
  }
  return btoa(bin)
}

type SttStatus = { status: string; reason?: string; latency_ms?: number }

export default function Room({ code, name, onLeave }: { code: string; name: string; onLeave: () => void }) {
  const localVideo = useRef<HTMLVideoElement>(null)
  const remoteVideo = useRef<HTMLVideoElement>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const localStream = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const chunksRef = useRef<Float32Array[]>([])
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const captureEpochRef = useRef<number>(0)
  const seqRef = useRef(0)
  const roleRef = useRef('guest')
  // VAD chunking config delivered in the WS join snapshot; applied to the
  // worklet when capture starts (and re-applied on every capture start).
  const vadRef = useRef<{ endpointSilenceMs?: number; maxChunkMs?: number }>({})
  const sendQueueRef = useRef<Promise<void>>(Promise.resolve())
  const transcriptEndRef = useRef<HTMLDivElement>(null)
  const seenTranscriptIds = useRef<Set<string>>(new Set())

  const [status, setStatus] = useState('connecting...')
  const [chat, setChat] = useState<{ id?: string; sender: string; body: string }[]>([])
  const [msg, setMsg] = useState('')
  const [transcripts, setTranscripts] = useState<{ id?: string; speaker: string; text: string }[]>([])
  const [muted, setMuted] = useState(false)
  const [camOff, setCamOff] = useState(false)
  const [webSpeechOn, setWebSpeechOn] = useState(false)
  const [recording, setRecording] = useState(false)
  const [role, setRole] = useState<string>('guest')
  const [sttStatus, setSttStatus] = useState<SttStatus | null>(null)
  const [modelInfo, setModelInfo] = useState('')
  const [railTab, setRailTab] = useState<'transcript' | 'chat' | 'copilot'>('transcript')
  const [showDiag, setShowDiag] = useState(false)
  const [copied, setCopied] = useState(false)
  const [peerName, setPeerName] = useState('Waiting…')
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => { roleRef.current = role }, [role])
  useEffect(() => { transcriptEndRef.current?.scrollIntoView({ block: 'end' }) }, [transcripts])

  async function startAudioCapture() {
    if (audioCtxRef.current) return
    // Recording can be resumed (from the room snapshot) before the main
    // effect has finished getUserMedia after a reload — wait, don't bail.
    for (let i = 0; i < 12; i++) {
      if (localStream.current?.getAudioTracks().length) break
      await new Promise((r) => setTimeout(r, 500))
    }
    const stream = localStream.current
    if (!stream || stream.getAudioTracks().length === 0) { console.error('no audio track'); return }
    const ctx = new AudioContext()
    const source = ctx.createMediaStreamSource(stream)
    const blob = new Blob([WORKLET_CODE], { type: 'application/javascript' })
    const url = URL.createObjectURL(blob)
    await ctx.audioWorklet.addModule(url)
    URL.revokeObjectURL(url)
    const node = new AudioWorkletNode(ctx, 'recorder-processor')
    // Apply the server's VAD tuning (endpoint silence / max chunk length).
    if (vadRef.current.endpointSilenceMs || vadRef.current.maxChunkMs) {
      node.port.postMessage({ type: 'config', ...vadRef.current })
    }
    node.port.onmessage = (e) => {
      const data = e.data
      if (data?.type === 'chunk' && Array.isArray(data.chunks)) {
        void queueChunk(data.chunks, data.sampleRate, data.speechMs)
      }
    }
    source.connect(node)
    // Some browsers suspend a worklet that has no destination connection.
    const mute = ctx.createGain()
    mute.gain.value = 0
    node.connect(mute).connect(ctx.destination)
    audioCtxRef.current = ctx
    workletNodeRef.current = node
    captureEpochRef.current = Date.now()
    console.log('audio capture started at', ctx.sampleRate, 'Hz (worklet VAD)')
  }

  function stopAudioCapture() {
    try { workletNodeRef.current?.port.postMessage('flush') } catch {}
    workletNodeRef.current?.disconnect()
    workletNodeRef.current = null
    audioCtxRef.current?.close()
    audioCtxRef.current = null
    chunksRef.current = []
  }

  function queueChunk(chunks: Float32Array[], sampleRate: number, speechMs: number) {
    sendQueueRef.current = sendQueueRef.current
      .then(() => sendChunk(chunks, sampleRate, speechMs))
      .catch((e) => console.error('send chunk failed', e))
  }

  function openWs(): WebSocket | null {
    const ws = wsRef.current
    return ws && ws.readyState === WebSocket.OPEN ? ws : null
  }

  async function sendChunk(chunks: Float32Array[], sampleRate: number, speechMs: number) {
    if (!openWs()) {
      // Mid-reconnect: wait briefly for the socket to come back so speech is
      // not silently lost, then give up on this chunk if the link stays down.
      for (let i = 0; i < 8; i++) {
        await new Promise((r) => setTimeout(r, 500))
        if (openWs()) break
      }
      if (!openWs()) {
        console.warn('audio chunk dropped: socket still closed')
        return
      }
    }
    let samples = float32Concat(chunks)
    if (samples.length < 800) return

    let maxAmp = 0, sumSq = 0
    for (let i = 0; i < samples.length; i++) {
      const a = Math.abs(samples[i])
      if (a > maxAmp) maxAmp = a
      sumSq += samples[i] * samples[i]
    }
    const rms = Math.sqrt(sumSq / samples.length)
    // Cheap client-side gate; the server re-checks with a proper VAD.
    if (maxAmp < 0.004 || rms < 0.0012) return

    samples = await resampleTo16k(samples, sampleRate)
    const wav = encodeWav(samples, 16000)
    const bytes = new Uint8Array(wav)
    const durationMs = Math.round(samples.length / 16)
    const endMs = Date.now() - captureEpochRef.current
    const startMs = Math.max(0, endMs - durationMs)
    const seq = seqRef.current++
    const speaker = roleRef.current === 'host' ? 'Interviewer' : 'Candidate'

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'audio-chunk',
        audio: b64FromBytes(bytes),
        suffix: '.wav',
        speaker,
        seq,
        start_ms: startMs,
        end_ms: endMs,
        speech_ms: speechMs,
      }))
      console.log(`sent ${durationMs}ms chunk (seq ${seq}), ${wav.byteLength} bytes`)
    }
  }

  useEffect(() => {
    if (recording) {
      startAudioCapture().catch((e) => {
        console.error('capture failed', e)
        setStatus('microphone unavailable')
      })
      if (intervalRef.current) clearInterval(intervalRef.current)
      // Safety net: force a flush if a worklet event is ever lost.
      intervalRef.current = setInterval(() => {
        try { workletNodeRef.current?.port.postMessage('flush') } catch {}
      }, 20000)
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
    let fallbackTimer: ReturnType<typeof setTimeout> | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    async function start() {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      })
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

      const send = (payload: unknown) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(payload))
      }

      async function offerPeer() {
        const p = pcRef.current
        if (!p) return
        // A stale offer/answer left over from a killed connection must never
        // block renegotiation — this was the "room stops working after a
        // refresh" bug; roll it back, then start a fresh negotiation.
        if (p.signalingState !== 'stable') {
          await p.setLocalDescription({ type: 'rollback' } as unknown as RTCLocalSessionDescriptionInit)
        }
        // iceRestart makes the ICE layer re-route to the partner's NEW page.
        const offer = await p.createOffer({ iceRestart: true })
        await p.setLocalDescription(offer)
        send({ type: 'offer', sdp: p.localDescription })
      }

      function attach(ws: WebSocket, attempt: number) {
        wsRef.current = ws
        ws.onopen = () => setStatus('connected')
        const mergeTranscripts = (incoming: { id?: string; speaker: string; text: string }[]) => {
          setTranscripts((prev) => {
            const known = new Set(prev.map((t) => t.id))
            const fresh = incoming.filter((t) => !t.id || !known.has(t.id))
            if (!fresh.length) return prev
            for (const t of fresh) seenTranscriptIds.current.add(String(t.id ?? t.text))
            return [...prev, ...fresh]
          })
        }
        ws.onmessage = async (ev) => {
          const data = JSON.parse(ev.data)
          try {
            switch (data.type) {
              case 'joined': {
                if (data.role) setRole(data.role)
                if (data.stt) setModelInfo(`${data.stt.model} → ${data.stt.fallback}`)
                if (data.vad) vadRef.current = data.vad
                // Room state snapshot: recording flag survives a refresh.
                if (typeof data.recording === 'boolean') setRecording(data.recording)
                const others = (data.participants || []).filter((p: any) => p.name !== name)
                if (others.length > 0) setPeerName(others[0].name)
                // Hydrate transcript + chat history so a reloaded client
                // continues exactly where the meeting left off.
                try {
                  const [tRes, cRes] = await Promise.all([
                    fetch(`/api/rooms/${code}/transcript`),
                    fetch(`/api/rooms/${code}/chat`),
                  ])
                  if (tRes.ok) {
                    const rows = await tRes.json()
                    mergeTranscripts(rows.map((r: any) => ({ id: r.id, speaker: r.speaker, text: r.text })))
                  }
                  if (cRes.ok) {
                    const rows = await cRes.json()
                    setChat((prev) => {
                      const fresh = rows.filter((r: any) => !prev.some((c) => c.id === r.id))
                      return fresh.length
                        ? [...prev, ...fresh.map((r: any) => ({ id: r.id, sender: r.sender, body: r.body }))]
                        : prev
                    })
                  }
                } catch {}
                // The peer usually offers first (it received our 'join').
                // Fallback: if nothing was negotiated shortly after, offer
                // ourselves — rescues reloads when that broadcast got lost.
                if (others.length > 0) {
                  if (fallbackTimer) clearTimeout(fallbackTimer)
                  fallbackTimer = setTimeout(() => {
                    const p = pcRef.current
                    if (
                      p && !cancelled &&
                      p.signalingState === 'stable' && !p.currentRemoteDescription
                    ) {
                      offerPeer().catch((e) => console.error('fallback offer failed', e))
                    }
                  }, 2500)
                }
                break
              }
              case 'start-recording':
                setRecording(true)
                break
              case 'stop-recording':
                setRecording(false)
                break
              case 'stt-status':
                setSttStatus(data)
                break
              case 'join':
                // The partner (re)joined — reconnect our status and restart
                // the connection with a fresh offer even if our pc still
                // remembers a half-completed negotiation.
                setStatus('connected')
                if (data.name) setPeerName(data.name)
                await offerPeer()
                break
              case 'offer': {
                const p = pcRef.current
                if (!p) break
                if (p.signalingState === 'have-local-offer') {
                  // Simultaneous offers: yield ours and answer theirs.
                  await p.setLocalDescription({ type: 'rollback' } as unknown as RTCLocalSessionDescriptionInit)
                }
                if (p.signalingState === 'stable' || p.signalingState === 'have-remote-offer') {
                  await p.setRemoteDescription(new RTCSessionDescription(data.sdp))
                  const answer = await p.createAnswer()
                  await p.setLocalDescription(answer)
                  send({ type: 'answer', sdp: p.localDescription })
                }
                break
              }
              case 'answer': {
                const p = pcRef.current
                if (!p) break
                if (p.signalingState === 'have-local-offer') {
                  await p.setRemoteDescription(new RTCSessionDescription(data.sdp))
                }
                break
              }
              case 'ice-candidate':
                try { await pcRef.current?.addIceCandidate(data.candidate) } catch {}
                break
              case 'transcript': {
                const key = String(data.id ?? '')
                if (key && seenTranscriptIds.current.has(key)) break
                if (key) seenTranscriptIds.current.add(key)
                mergeTranscripts([{ id: data.id, speaker: data.speaker, text: data.text }])
                break
              }
              case 'chat': {
                // Server broadcasts back to the sender too; dedupe by id.
                setChat((prev) => {
                  if (data.id && prev.some((c) => c.id === data.id)) return prev
                  return [...prev, { id: data.id, sender: data.sender, body: data.body }]
                })
                break
              }
              case 'error':
                console.error('server: ' + (data.message || 'unknown error'))
                break
              case 'leave':
                // Ignore our own stale leave (fired by the old socket after a
                // reload); only a *different* person leaving is meaningful.
                if (data.name && data.name !== name) { setStatus('peer left'); setPeerName('Waiting…') }
                break
            }
          } catch (e) {
            console.error('ws message handler error', e)
          }
        }
        ws.onclose = () => {
          setStatus('disconnected')
          // Lightweight auto-reconnect: the WebRTC media channel survives the
          // socket drop; this restores live updates and (via the backend's
          // fresh 'join' broadcast) triggers renegotiation to the new page.
          if (!cancelled && attempt < 5) {
            retryTimer = setTimeout(() => { if (!cancelled) connect(attempt + 1) }, 1500 * (attempt + 1))
          }
        }
      }

      function connect(attempt: number) {
        const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        try {
          const ws = new WebSocket(`${wsProto}//${location.host}/ws/${code}?name=${encodeURIComponent(name)}`)
          attach(ws, attempt)
        } catch (e) {
          console.error('ws connect failed', e)
          if (!cancelled && attempt < 5) {
            retryTimer = setTimeout(() => { if (!cancelled) connect(attempt + 1) }, 1500 * (attempt + 1))
          }
        }
      }
      connect(0)
    }
    start().catch((e) => { console.error(e); setStatus('could not access camera/microphone') })
    return () => {
      cancelled = true
      if (fallbackTimer) clearTimeout(fallbackTimer)
      if (retryTimer) clearTimeout(retryTimer)
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
      stopAudioCapture()
      pcRef.current?.close()
      wsRef.current?.close()
      localStream.current?.getTracks().forEach(t => t.stop())
    }
  }, [code, name])

  // Web Speech API: free, real-time, browser-native STT (fallback only).
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
            wsRef.current.send(JSON.stringify({ type: 'transcript', speaker: roleRef.current === 'host' ? 'Interviewer' : 'Candidate', text }))
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
    const next = !muted
    localStream.current?.getAudioTracks().forEach(t => (t.enabled = !next))
    setMuted(next)
  }
  function toggleCam() {
    const next = !camOff
    localStream.current?.getVideoTracks().forEach(t => (t.enabled = !next))
    setCamOff(next)
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
      wsRef.current?.send(JSON.stringify({
        type: 'audio-chunk',
        audio: b64FromBytes(buf),
        suffix: '.wav',
        speaker: roleRef.current === 'host' ? 'Interviewer' : 'Candidate',
        seq: seqRef.current++,
      }))
      console.log('test wav sent', buf.length)
    } catch (e) { console.error('test wav failed', e) }
  }

  const statusDot =
    status === 'connected' ? 'connected'
      : status === 'connecting...' ? 'connecting'
        : status === 'peer left' ? 'peers'
          : 'disconnected'

  function copyCode() {
    try {
      void navigator.clipboard?.writeText(code).catch(() => { /* clipboard unavailable */ })
      setCopied(true)
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
      copiedTimer.current = setTimeout(() => setCopied(false), 1600)
    } catch { /* clipboard unavailable */ }
  }

  function recordToggle() {
    const next = !recording
    setRecording(next)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: next ? 'start-recording' : 'stop-recording' }))
    }
  }

  const statusText = status.charAt(0).toUpperCase() + status.slice(1).replace(/\.\.\.$/, '…')

  return (
    <div className="room">
      {/* ── top deck ─────────────────────────────────────────── */}
      <header className="room-top">
        <div className="brand">
          <span className="eq" aria-hidden="true"><i /><i /><i /><i /><i /></span>
          Interview Room
        </div>

        <div className="top-mid">
          <button
            className={`slate${copied ? ' copied' : ''}`}
            onClick={copyCode}
            title="Copy room code"
            aria-label={`Copy room code ${code}`}
          >
            <span className="mono">{code}</span>
            <kbd>{copied ? 'copied' : 'copy'}</kbd>
          </button>
          {recording && (
            <span className="chip chip-rec" aria-label="Recording in progress">
              <span className="rec-point" /> REC
            </span>
          )}
          <span className="chip chip-status">
            <span className="dot" data-state={statusDot} />
            {statusText}
          </span>
        </div>

        <button className="btn btn-danger btn-sm" onClick={onLeave}>
          <IconLeave /> Leave
        </button>
      </header>

      <div className="room-body">
        {/* ── stage ──────────────────────────────────────────── */}
        <section className="stage-col">
          <div className="stage">
            <figure className="tile tile-remote vf">
              <span className="vf-c tl" /><span className="vf-c tr" /><span className="vf-c bl" /><span className="vf-c br" />
              <video ref={remoteVideo} autoPlay playsInline />
              <figcaption className="tile-label">{peerName}</figcaption>
            </figure>
            <figure className="tile tile-local vf">
              <span className="vf-c tl" /><span className="vf-c tr" /><span className="vf-c bl" /><span className="vf-c br" />
              <video ref={localVideo} autoPlay muted playsInline />
              {(camOff || muted) && (
                <span className="tile-badge">
                  {camOff ? 'CAMERA OFF' : 'MUTED'}
                </span>
              )}
              <figcaption className="tile-label">You · {name}</figcaption>
            </figure>
          </div>

          <div className="deck">
            <div className="ctl-bar" role="toolbar" aria-label="Meeting controls">
              <button
                className={`ctl-btn${muted ? ' is-live' : ''}`}
                onClick={toggleMute}
                title={muted ? 'Unmute microphone' : 'Mute microphone'}
                aria-label={muted ? 'Unmute microphone' : 'Mute microphone'}
                aria-pressed={muted}
              >
                {muted ? <IconMicOff size={21} /> : <IconMic size={21} />}
              </button>
              <button
                className={`ctl-btn${camOff ? ' is-live' : ''}`}
                onClick={toggleCam}
                title={camOff ? 'Turn camera on' : 'Turn camera off'}
                aria-label={camOff ? 'Turn camera on' : 'Turn camera off'}
                aria-pressed={camOff}
              >
                {camOff ? <IconCamOff size={21} /> : <IconCam size={21} />}
              </button>
              <button
                className="ctl-btn"
                onClick={() => void shareScreen()}
                title="Share your screen"
                aria-label="Share your screen"
              >
                <IconScreen size={21} />
              </button>
              {role === 'host' && (
                <button
                  className={`ctl-btn ctl-record${recording ? ' is-live' : ''}`}
                  onClick={recordToggle}
                  title={recording ? 'Stop recording' : 'Start recording'}
                  aria-label={recording ? 'Stop recording' : 'Start recording'}
                  aria-pressed={recording}
                >
                  {recording ? <IconStop size={19} /> : <IconRecord size={21} />}
                </button>
              )}
            </div>
            <button className="btn btn-danger leave" onClick={onLeave}>
              <IconLeave /> Leave call
            </button>
          </div>

          {role === 'host' && (
            <div className="diag">
              <button
                className="diag-toggle"
                onClick={() => setShowDiag((v) => !v)}
                aria-expanded={showDiag}
              >
                <span className="shevron" aria-hidden="true">▸</span>
                Diagnostics
              </button>
              {showDiag && (
                <div className="diag-tools">
                  <button
                    className="chip chip-action"
                    onClick={() => { try { workletNodeRef.current?.port.postMessage('flush') } catch {} }}
                    title="Flush any buffered speech to the transcriber now"
                  >
                    Send audio now
                  </button>
                  <button className="chip chip-action" onClick={() => void testSttWav()}>
                    Test STT (wav)
                  </button>
                  <button className="chip chip-action" onClick={toggleWebSpeech} aria-pressed={webSpeechOn}>
                    {webSpeechOn ? 'Browser STT: on' : 'Browser STT: off'}
                  </button>
                  {modelInfo && <span className="chip" title="Speech-to-text model in use">STT {modelInfo}</span>}
                  {sttStatus && (
                    <span className="chip chip-stt">
                      <span
                        className="dot"
                        data-state={sttStatus.status === 'ok' ? 'ok' : sttStatus.status}
                        style={sttStatus.status === 'ok' ? { background: 'var(--live)' } : undefined}
                      />
                      {sttStatus.status}
                      {typeof sttStatus.latency_ms === 'number' ? ` · ${sttStatus.latency_ms}ms` : ''}
                    </span>
                  )}
                </div>
              )}
            </div>
          )}
        </section>

        {/* ── right rail ─────────────────────────────────────── */}
        <aside className="rail" aria-label="Meeting panels">
          <div className="rail-tabs" role="tablist">
            <button
              role="tab"
              className={`rail-tab${railTab === 'transcript' ? ' is-active' : ''}`}
              aria-selected={railTab === 'transcript'}
              onClick={() => setRailTab('transcript')}
            >
              Transcript
            </button>
            <button
              role="tab"
              className={`rail-tab${railTab === 'chat' ? ' is-active' : ''}`}
              aria-selected={railTab === 'chat'}
              onClick={() => setRailTab('chat')}
            >
              Chat{chat.length > 0 ? ` · ${chat.length}` : ''}
            </button>
            {role === 'host' && (
              <button
                role="tab"
                className={`rail-tab${railTab === 'copilot' ? ' is-active' : ''}`}
                aria-selected={railTab === 'copilot'}
                onClick={() => setRailTab('copilot')}
              >
                Copilot
              </button>
            )}
          </div>

          {railTab === 'transcript' && (
            <div className="rail-panel">
              <div className="rail-scroll scroll-pane">
                {transcripts.length === 0 ? (
                  <div className="rail-empty">
                    <IconWave size={26} />
                    <p>Captions appear here once speech is captured — each utterance is tagged by speaker.</p>
                  </div>
                ) : (
                  transcripts.map((t, i) => (
                    <div className="t-row" key={t.id || i}>
                      <span
                        className={`t-speaker ${
                          t.speaker === 'Interviewer' ? 'host'
                            : t.speaker === 'Candidate' ? 'candidate' : 'other'
                        }`}
                      >
                        {t.speaker}
                      </span>
                      <p className="t-text">{t.text}</p>
                    </div>
                  ))
                )}
                <div ref={transcriptEndRef} />
              </div>
            </div>
          )}

          {railTab === 'chat' && (
            <div className="rail-panel">
              <div className="rail-scroll scroll-pane">
                {chat.length === 0 ? (
                  <div className="rail-empty">
                    <IconWave size={26} />
                    <p>No messages yet. Say hello — the conversation is visible to both of you.</p>
                  </div>
                ) : (
                  chat.map((c, i) => (
                    <div className="c-row" key={c.id || i}>
                      <span
                        className={`c-avatar ${c.sender === name ? 'me' : 'them'}`}
                        aria-hidden="true"
                      >
                        {c.sender.trim().charAt(0).toUpperCase() || '?'}
                      </span>
                      <div>
                        <div className="c-meta">
                          <span className="c-name">{c.sender}{c.sender === name ? ' (you)' : ''}</span>
                        </div>
                        <p className="c-body">{c.body}</p>
                      </div>
                    </div>
                  ))
                )}
              </div>
              <form
                className="rail-foot"
                onSubmit={(e) => { e.preventDefault(); sendChat() }}
              >
                <div className="chat-row">
                  <input
                    className="input"
                    placeholder="Type a message…"
                    value={msg}
                    onChange={(e) => setMsg(e.target.value)}
                    aria-label="Chat message"
                  />
                  <button className="btn btn-primary btn-sm" onClick={sendChat} disabled={!msg.trim()}>
                    <IconSend /> Send
                  </button>
                </div>
              </form>
            </div>
          )}

          {railTab === 'copilot' && role === 'host' && (
            <Copilot code={code} />
          )}
        </aside>
      </div>
    </div>
  )
}
