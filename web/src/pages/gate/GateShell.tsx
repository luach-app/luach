import type { ReactNode } from 'react'
import { Logo } from '../../components/Logo'

export function GateShell({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <main className="safe-top safe-bottom safe-x flex min-h-dvh items-center justify-center px-5 py-10">
      <div className="fade-up w-full max-w-sm">
        <Logo size="lg" className="mb-8 justify-center" />
        <div className="card px-6 py-6 shadow-[var(--shadow)]">
          <h1 className="text-xl font-semibold">{title}</h1>
          {subtitle ? <p className="mt-1 text-sm text-muted">{subtitle}</p> : null}
          <div className="mt-5">{children}</div>
        </div>
        {/* Plain links, full page loads: the two pages are outside the app. */}
        <p className="mt-6 text-center text-sm text-muted">
          <a href="/about" className="hover:text-accent-text">
            About luach
          </a>
          {' · '}
          <a href="/privacy" className="hover:text-accent-text">
            Privacy
          </a>
        </p>
      </div>
    </main>
  )
}
