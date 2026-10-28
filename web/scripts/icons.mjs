// Generates public/icon-*.png: a gold rounded square with the letters לוח.
// Pure Node (zlib + crc32), no image dependencies. Run: node scripts/icons.mjs
import { deflateSync, crc32 } from 'node:zlib'
import { writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = join(here, '..', 'public')

const GOLD = [0xf4, 0xb9, 0x42]
const INK = [0x1a, 0x14, 0x00]

// Glyph strokes in a unit box (x0, y0, x1, y1), y grows downward.
// Visual order left→right is ח ו ל because Hebrew reads right→left.
const GLYPHS = {
  lamed: [
    [0.58, 0.0, 0.8, 0.5], // tall stem above the roof
    [0.1, 0.36, 0.8, 0.52], // roof
    [0.1, 0.36, 0.32, 0.92], // hanging leg
    [0.1, 0.78, 0.5, 0.92], // foot
  ],
  vav: [
    [0.3, 0.3, 0.72, 0.45], // cap
    [0.38, 0.3, 0.62, 0.92], // stroke
  ],
  chet: [
    [0.08, 0.3, 0.92, 0.45], // bar
    [0.08, 0.3, 0.3, 0.92], // left leg
    [0.7, 0.3, 0.92, 0.92], // right leg
  ],
}

function roundedSquareCoverage(x, y, size, radius) {
  // Signed distance to a rounded square centred in [0,size]; returns 0..1 coverage.
  const half = size / 2
  const dx = Math.abs(x - half) - (half - radius)
  const dy = Math.abs(y - half) - (half - radius)
  const ox = Math.max(dx, 0)
  const oy = Math.max(dy, 0)
  const dist = Math.hypot(ox, oy) + Math.min(Math.max(dx, dy), 0) - radius
  return Math.min(1, Math.max(0, 0.5 - dist))
}

function insideGlyphs(px, py, size, safe) {
  // Lay out three glyphs inside the safe box, each `gw` wide with a gap.
  const box = size * safe
  const left = (size - box) / 2
  const top = (size - box) / 2
  const gap = box * 0.06
  const gw = (box - gap * 2) / 3
  const gh = box * 0.72
  const gy = top + (box - gh) / 2
  const order = ['chet', 'vav', 'lamed']
  for (let i = 0; i < 3; i++) {
    const gx = left + i * (gw + gap)
    const u = (px - gx) / gw
    const v = (py - gy) / gh
    if (u < 0 || u > 1 || v < 0 || v > 1) continue
    for (const [x0, y0, x1, y1] of GLYPHS[order[i]]) {
      if (u >= x0 && u <= x1 && v >= y0 && v <= y1) return true
    }
  }
  return false
}

export function render(size, { maskable, safe = maskable ? 0.56 : 0.66 }) {
  const ss = 4 // supersampling factor
  const radius = maskable ? 0 : size * 0.22
  const rgba = Buffer.alloc(size * size * 4)
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let cover = 0
      let ink = 0
      for (let sy = 0; sy < ss; sy++) {
        for (let sx = 0; sx < ss; sx++) {
          const px = x + (sx + 0.5) / ss
          const py = y + (sy + 0.5) / ss
          const c = maskable ? 1 : roundedSquareCoverage(px, py, size, radius)
          cover += c
          if (c > 0 && insideGlyphs(px, py, size, safe)) ink += 1
        }
      }
      const n = ss * ss
      const alpha = cover / n
      const t = ink / n
      const o = (y * size + x) * 4
      rgba[o] = Math.round(GOLD[0] * (1 - t) + INK[0] * t)
      rgba[o + 1] = Math.round(GOLD[1] * (1 - t) + INK[1] * t)
      rgba[o + 2] = Math.round(GOLD[2] * (1 - t) + INK[2] * t)
      rgba[o + 3] = Math.round(alpha * 255)
    }
  }
  return rgba
}

function chunk(type, data) {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length)
  const typeBuf = Buffer.from(type, 'ascii')
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])) >>> 0)
  return Buffer.concat([len, typeBuf, data, crc])
}

// `opaque` drops the alpha channel: App Store icons must not carry one.
export function png(size, rgba, { opaque = false } = {}) {
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = opaque ? 2 : 6 // RGB : RGBA
  ihdr[10] = 0
  ihdr[11] = 0
  ihdr[12] = 0
  const bpp = opaque ? 3 : 4
  const stride = size * bpp
  const raw = Buffer.alloc((stride + 1) * size)
  for (let y = 0; y < size; y++) {
    raw[y * (stride + 1)] = 0 // filter: none
    for (let x = 0; x < size; x++) {
      rgba.copy(raw, y * (stride + 1) + 1 + x * bpp, (y * size + x) * 4, (y * size + x) * 4 + bpp)
    }
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

// Imported by ios/scripts/icon.mjs for the app icon; only writes when run itself.
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  mkdirSync(outDir, { recursive: true })
  const targets = [
    ['icon-192.png', 192, { maskable: false }],
    ['icon-512.png', 512, { maskable: false }],
    ['icon-512-maskable.png', 512, { maskable: true }],
  ]
  for (const [name, size, opts] of targets) {
    writeFileSync(join(outDir, name), png(size, render(size, opts)))
  }
  console.log(`icons: wrote ${targets.map((t) => t[0]).join(', ')} to public/`)
}
