import { describe, expect, it, vi } from 'vitest'
import { streamAgent } from '../sse'
import { ApiError } from '../api'
import type { StreamFrame } from '../types'

/** A response whose body arrives in whatever pieces the test chooses. */
function streamed(chunks: string[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const enc = new TextEncoder()
      for (const c of chunks) controller.enqueue(enc.encode(c))
      controller.close()
    },
  })
  return new Response(body, { status, headers: { 'Content-Type': 'text/event-stream' } })
}

const collect = async (chunks: string[]) => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamed(chunks))
  const frames: StreamFrame[] = []
  await streamAgent({ text: 'what is on today?' }, (f) => frames.push(f))
  return frames
}

describe('reading the agent’s stream', () => {
  it('hands over each frame in order', async () => {
    const frames = await collect([
      'data: {"type":"session","thread_id":"t1"}\n\n',
      'data: {"type":"token","text":"Added "}\n\n',
      'data: {"type":"token","text":"it."}\n\n',
      'data: {"type":"done","reply":"Added it."}\n\n',
    ])
    expect(frames.map((f) => f.type)).toEqual(['session', 'token', 'token', 'done'])
  })

  it('does not care where the network split the bytes', async () => {
    const frames = await collect(['data: {"type":"tok', 'en","text":"half"}\n', '\ndata: {"type":"done"}\n\n'])
    expect(frames).toHaveLength(2)
    expect(frames[0]).toMatchObject({ type: 'token', text: 'half' })
  })

  it('reassembles a frame written across several data lines', async () => {
    const frames = await collect(['data: {"type":"token",\ndata: "text":"joined"}\n\n'])
    expect(frames[0]).toMatchObject({ type: 'token', text: 'joined' })
  })

  it('skips a frame that is not JSON rather than dying mid-conversation', async () => {
    const frames = await collect(['data: not json\n\n', 'data: {"type":"done"}\n\n'])
    expect(frames.map((f) => f.type)).toEqual(['done'])
  })

  it('reports the server’s own words when the stream is refused', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: 'sign in first' }), { status: 401, headers: { 'Content-Type': 'application/json' } }),
    )
    await expect(streamAgent({ text: 'hi' }, () => {})).rejects.toMatchObject({ status: 401, message: 'sign in first' })
  })

  it('still says something when the refusal is not JSON', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('<html>502</html>', { status: 502 }))
    await expect(streamAgent({ text: 'hi' }, () => {})).rejects.toBeInstanceOf(ApiError)
  })

  it('sends the thread it is continuing', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamed(['data: {"type":"done"}\n\n']))
    await streamAgent({ text: 'and tomorrow?', thread_id: 't1' }, () => {})
    expect(JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      text: 'and tomorrow?',
      thread_id: 't1',
    })
  })
})
