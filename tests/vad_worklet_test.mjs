/**
 * Deterministic test for the RecorderProcessor AudioWorklet in Room.tsx.
 *
 * Extracts the real WORKLET_CODE string from the component source, evaluates
 * it against mocked AudioWorkletProcessor globals, and feeds synthetic mic
 * frames to assert the endpointing behaviour:
 *
 *   1. a 700 ms mid-sentence pause no longer splits one utterance into two
 *      chunks (the jumbled-transcript bug) — one chunk is emitted at the
 *      1200 ms endpoint instead
 *   2. the 15 s max-chunk cap still cuts a continuous monologue
 *   3. 'flush' captures the tail when capture stops mid-utterance
 *   4. a {type:'config'} message retunes the endpoint (server-driven tuning)
 *
 * Run:  node tests/vad_worklet_test.mjs
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const roomTsx = fileURLToPath(new URL('../frontend/src/pages/Room.tsx', import.meta.url))
const src = readFileSync(roomTsx, 'utf8')
const marker = 'const WORKLET_CODE = `'
const start = src.indexOf(marker) + marker.length
const end = src.indexOf('`', start)
if (start < marker.length || end < 0) throw new Error('WORKLET_CODE not found in Room.tsx')
const code = src.slice(start, end)

// --- mock the AudioWorklet host environment ---
globalThis.sampleRate = 48000
globalThis.AudioWorkletProcessor = class {
  constructor() {
    this.port = { onmessage: null, postMessage: () => {} }
  }
}
let captured = null
globalThis.registerProcessor = (_name, cls) => { captured = cls }

new Function(code)()
if (!captured) throw new Error('registerProcessor was never called')

const FRAME = 128
const FRAME_MS = (FRAME / 48000) * 1000 // 2.667 ms per quantum at 48 kHz

function makeProcessor() {
  const proc = new captured()
  const messages = []
  proc.port.postMessage = (m) => messages.push(m)
  const send = (data) => proc.port.onmessage({ data })
  return { proc, messages, send }
}

function feed(proc, ms, kind) {
  const n = Math.round(ms / FRAME_MS)
  for (let i = 0; i < n; i++) {
    const frame = new Float32Array(FRAME)
    if (kind === 'speech') {
      for (let j = 0; j < FRAME; j++) {
        frame[j] = 0.05 * Math.sin(2 * Math.PI * 220 * ((i * FRAME + j) / 48000))
      }
    }
    proc.process([[frame]])
  }
}

let failures = 0
function check(name, ok, detail) {
  console.log(`  ${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`)
  if (!ok) failures++
}

// --- Test 1: a 700 ms mid-sentence pause must NOT split the utterance ---
{
  const { proc, messages } = makeProcessor()
  feed(proc, 1000, 'speech')
  feed(proc, 700, 'silence')   // old 480 ms endpoint cut here -> jumbled text
  feed(proc, 1000, 'speech')
  feed(proc, 1300, 'silence')  // crosses the 1200 ms endpoint -> emit
  const chunks = messages.filter((m) => m.type === 'chunk')
  const speech = chunks[0]?.speechMs ?? 0
  check('700ms pause does not split the utterance', chunks.length === 1,
        `chunks=${chunks.length}`)
  check('emitted once at the 1200ms endpoint with all speech',
        speech >= 1900 && speech <= 2100, `speechMs=${Math.round(speech)}`)
}

// --- Test 2: the 15 s max-chunk cap still cuts a continuous monologue ---
{
  const { proc, messages } = makeProcessor()
  feed(proc, 16000, 'speech')
  const chunks = messages.filter((m) => m.type === 'chunk')
  const speech = chunks[0]?.speechMs ?? 0
  check('continuous monologue is capped at ~15s', chunks.length >= 1 &&
        speech >= 14500 && speech <= 15500,
        `chunks=${chunks.length} speechMs=${Math.round(speech)}`)
}

// --- Test 3: flush captures the tail when capture stops mid-utterance ---
{
  const { proc, messages, send } = makeProcessor()
  feed(proc, 600, 'speech')
  send('flush')
  const chunks = messages.filter((m) => m.type === 'chunk')
  const speech = chunks[0]?.speechMs ?? 0
  check('flush emits the trailing partial utterance', chunks.length === 1 &&
        speech >= 550 && speech <= 650, `speechMs=${Math.round(speech)}`)
}

// --- Test 4: a config message retunes the endpoint (server-driven) ---
{
  const { proc, messages, send } = makeProcessor()
  send({ type: 'config', endpointSilenceMs: 480 })
  feed(proc, 1000, 'speech')
  feed(proc, 700, 'silence')  // now >= 480 -> emit mid-utterance again
  feed(proc, 1000, 'speech')
  feed(proc, 600, 'silence')  // >= 480 -> emit the second half
  const chunks = messages.filter((m) => m.type === 'chunk')
  check('config endpointSilenceMs=480 restores the split behaviour',
        chunks.length === 2, `chunks=${chunks.length}`)
}

// --- Test 5: bad config values are ignored (floor guards) ---
{
  const { proc, send } = makeProcessor()
  send({ type: 'config', endpointSilenceMs: 10, maxChunkMs: 1 })
  check('config below the floors is rejected',
        proc.endpointSilenceMs === 1200 && proc.maxChunkMs === 15000,
        `endpoint=${proc.endpointSilenceMs} max=${proc.maxChunkMs}`)
}

console.log(failures ? `\n${failures} FAILED` : '\nAll worklet endpointing checks passed')
process.exit(failures ? 1 : 0)
