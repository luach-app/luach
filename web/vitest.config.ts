import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    // The booking page renders times in the *visitor's* zone, so a test that
    // reads "9:00" passes in New York and fails on a UTC runner. Pin the zone
    // and the suite says the same thing on every machine.
    env: { TZ: 'America/New_York' },
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'text'],
      // What a person can break: the logic and the screens. Icons are paths,
      // main.tsx is three lines of boot, and the test helpers test nothing.
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/main.tsx', 'src/components/Icons.tsx', 'src/test/**', 'src/**/*.d.ts'],
      // Set at what the suite actually holds, so a regression fails here rather
      // than in someone's browser. Functions sit lower than lines on purpose:
      // every inline handler counts as one, and a handler with no behaviour of
      // its own is not worth a test to satisfy a number.
      // Re-floored 2026-09-20 with vitest 4: its v8 provider maps coverage through the
      // AST and counts more of the same code as uncovered (84/84/74 became 76/73/65 with
      // no test changed). The floor's meaning is unchanged: today's number, not a target.
      thresholds: { lines: 76, statements: 73, branches: 65, functions: 58 },
    },
  },
})
