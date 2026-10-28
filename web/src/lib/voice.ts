/** Microphone capture with MediaRecorder; the transcript goes to the composer for review. */

export const MAX_AUDIO_BYTES = 12 * 1024 * 1024

export function voiceSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined'
  )
}

export function pickMimeType(): string {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']
  for (const c of candidates) {
    if (MediaRecorder.isTypeSupported(c)) return c
  }
  return ''
}

/** `audio/webm;codecs=opus` → `audio/webm` — the Content-Type the API lists. */
export function baseContentType(mime: string): string {
  const base = mime.split(';')[0]?.trim()
  return base || 'audio/webm'
}

export interface Recording {
  blob: Blob
  contentType: string
  durationMs: number
}

export class Recorder {
  private stream: MediaStream | null = null
  private recorder: MediaRecorder | null = null
  private chunks: BlobPart[] = []
  private startedAt = 0
  private mime = ''

  get active(): boolean {
    return this.recorder?.state === 'recording'
  }

  async start(): Promise<void> {
    if (this.active) return
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    this.mime = pickMimeType()
    this.recorder = this.mime
      ? new MediaRecorder(this.stream, { mimeType: this.mime })
      : new MediaRecorder(this.stream)
    this.chunks = []
    this.recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data.size > 0) this.chunks.push(e.data)
    }
    this.startedAt = Date.now()
    this.recorder.start(250)
  }

  stop(): Promise<Recording> {
    return new Promise((resolve, reject) => {
      const rec = this.recorder
      if (!rec || rec.state === 'inactive') {
        this.release()
        reject(new Error('Not recording.'))
        return
      }
      rec.onstop = () => {
        const type = rec.mimeType || this.mime || 'audio/webm'
        const blob = new Blob(this.chunks, { type })
        const durationMs = Date.now() - this.startedAt
        this.release()
        resolve({ blob, contentType: baseContentType(type), durationMs })
      }
      rec.onerror = () => {
        this.release()
        reject(new Error('Recording failed.'))
      }
      rec.stop()
    })
  }

  cancel(): void {
    try {
      if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop()
    } catch {
      /* already stopped */
    }
    this.release()
  }

  private release() {
    this.stream?.getTracks().forEach((t) => t.stop())
    this.stream = null
    this.recorder = null
    this.chunks = []
  }
}
