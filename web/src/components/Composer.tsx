import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { errorMessage, voice } from '../lib/api'
import { MAX_AUDIO_BYTES, Recorder, voiceSupported } from '../lib/voice'
import { Button } from './Button'
import { MicIcon, SendIcon, StopIcon } from './Icons'

interface Props {
  disabled?: boolean
  /** A turn is being answered: the send button becomes Stop. */
  streaming?: boolean
  onStop?: () => void
  micAvailable: boolean
  onSend: (text: string) => void
  onError: (msg: string) => void
  /** Text pushed in from outside (suggestion chips). */
  seed?: { text: string; nonce: number }
}

type MicState = 'idle' | 'recording' | 'transcribing'

export function Composer({ disabled = false, streaming = false, onStop, micAvailable, onSend, onError, seed }: Props) {
  const [text, setText] = useState('')
  const [mic, setMic] = useState<MicState>('idle')
  const [fromVoice, setFromVoice] = useState(false)
  const areaRef = useRef<HTMLTextAreaElement>(null)
  const recorder = useRef<Recorder | null>(null)

  useEffect(() => {
    if (seed?.text) {
      setText(seed.text)
      areaRef.current?.focus()
    }
  }, [seed])

  useEffect(() => {
    const el = areaRef.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [text])

  useEffect(() => () => recorder.current?.cancel(), [])

  const send = () => {
    const t = text.trim()
    if (!t || disabled) return
    onSend(t)
    setText('')
    setFromVoice(false)
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }

  const toggleMic = async () => {
    if (mic === 'transcribing') return
    if (mic === 'recording') {
      setMic('transcribing')
      try {
        const rec = await recorder.current!.stop()
        if (rec.durationMs < 400) throw new Error('That was too short — hold the mic a little longer.')
        if (rec.blob.size > MAX_AUDIO_BYTES) throw new Error('That recording is too long (over 12 MB).')
        const { text: transcript } = await voice.transcribe(rec.blob, rec.contentType)
        setText((prev) => (prev.trim() ? `${prev.trim()} ${transcript}` : transcript))
        setFromVoice(true)
        areaRef.current?.focus()
      } catch (e) {
        onError(errorMessage(e) || 'Could not transcribe that.')
      } finally {
        setMic('idle')
      }
      return
    }
    try {
      recorder.current ??= new Recorder()
      await recorder.current.start()
      setMic('recording')
    } catch (e) {
      const err = e as { name?: string }
      onError(err?.name === 'NotAllowedError' ? 'Microphone access was not allowed.' : errorMessage(e) || 'Could not start the microphone.')
      setMic('idle')
    }
  }

  const showMic = micAvailable && voiceSupported()
  return (
    <div className="relative">
      <div className="flex items-end gap-2 rounded-3xl border border-line-strong bg-surface p-1.5 pl-4 shadow-[var(--shadow)]">
        <textarea
          ref={areaRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setFromVoice(false)
          }}
          onKeyDown={onKey}
          rows={1}
          dir="auto"
          placeholder={mic === 'recording' ? 'Listening…' : mic === 'transcribing' ? 'Transcribing…' : 'Ask luach…'}
          aria-label="Message"
          disabled={disabled}
          className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent py-2.5 text-[16px] placeholder:text-muted/70 focus:outline-none"
        />
        {showMic ? (
          <Button
            type="button"
            size="icon"
            variant={mic === 'recording' ? 'danger' : 'ghost'}
            aria-label={mic === 'recording' ? 'Stop recording' : mic === 'transcribing' ? 'Transcribing' : 'Record a voice message'}
            aria-pressed={mic === 'recording'}
            onClick={toggleMic}
            busy={mic === 'transcribing'}
            disabled={disabled}
            className={mic === 'recording' ? 'rec-ring' : ''}
          >
            {mic === 'recording' ? <StopIcon /> : mic === 'transcribing' ? null : <MicIcon />}
          </Button>
        ) : null}
        {streaming && onStop ? (
          <Button type="button" size="icon" variant="ghost" aria-label="Stop answering" onClick={onStop}>
            <StopIcon />
          </Button>
        ) : (
        <Button
          type="button"
          size="icon"
          variant={text.trim() ? 'primary' : 'ghost'}
          aria-label={fromVoice ? 'Send the transcript' : 'Send'}
          onClick={send}
          disabled={disabled || !text.trim()}
          className={fromVoice ? 'ring-2 ring-accent/60' : ''}
        >
          <SendIcon />
        </Button>
        )}
      </div>
    </div>
  )
}
