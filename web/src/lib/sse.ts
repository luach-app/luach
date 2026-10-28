import { ApiError } from './api'
import type { StreamFrame } from './types'

/**
 * POST /api/agent/stream and hand every `data: {json}` frame to `onFrame`.
 * Uses fetch + ReadableStream (EventSource cannot POST or carry cookies reliably).
 */
export async function streamAgent(
  body: { text: string; thread_id?: string; model?: string },
  onFrame: (frame: StreamFrame) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/agent/stream', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    let message = `Request failed (${res.status}).`
    try {
      const data = (await res.json()) as { error?: string }
      if (data.error) message = data.error
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message)
  }
  if (!res.body) throw new Error('The server sent an empty stream.')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let dataLines: string[] = []

  const flush = () => {
    if (dataLines.length === 0) return
    const raw = dataLines.join('\n')
    dataLines = []
    if (!raw.trim()) return
    try {
      onFrame(JSON.parse(raw) as StreamFrame)
    } catch {
      /* skip malformed frame */
    }
  }

  const consume = (line: string) => {
    if (line === '') {
      flush()
      return
    }
    if (line.startsWith(':')) return // comment / keepalive
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''))
    }
    // `event:` / `id:` / `retry:` lines are ignored — the type lives inside the JSON.
  }

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, idx).replace(/\r$/, '')
      buffer = buffer.slice(idx + 1)
      consume(line)
    }
  }
  buffer += decoder.decode()
  if (buffer) consume(buffer.replace(/\r$/, ''))
  flush()
}
