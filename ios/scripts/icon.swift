// Draws luach's app icon: a calendar page on warm amber, the word לוח on it.
// Runs on the Mac (it needs AppKit and the system's rounded Hebrew):
//
//   swift ios/scripts/icon.swift <out.png> [page|word]
//
// "page" (the default) is the icon; "word" is the bare word on amber, kept for comparison.
// Opaque and full bleed: iOS rounds the corners itself, and the App Store refuses an alpha channel.
import AppKit

let size: CGFloat = 1024
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon-1024.png"
let style = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "page"

func rgb(_ hex: UInt32, _ a: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}

// The web app's tokens: --accent #f4b942 (dark) / #d39a1a (light), ink #1a1400, night #0f0e14.
let amberTop = rgb(0xF8C65A), amberBottom = rgb(0xD8901A), ink = rgb(0x1F1A12), paper = rgb(0xFFFDF7)

func roundedFont(_ size: CGFloat, _ weight: NSFont.Weight) -> NSFont {
    let base = NSFont.systemFont(ofSize: size, weight: weight)
    let desc = base.fontDescriptor.withDesign(.rounded) ?? base.fontDescriptor
    return NSFont(descriptor: desc, size: size) ?? base
}

// No alpha channel at all: the pixels are RGB with the fourth byte skipped.
let cg = CGContext(data: nil, width: Int(size), height: Int(size), bitsPerComponent: 8, bytesPerRow: 0,
                   space: CGColorSpace(name: CGColorSpace.sRGB)!,
                   bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(cgContext: cg, flipped: false)

// Amber, lit from the top left.
let bg = NSGradient(colors: [amberTop, amberBottom])!
bg.draw(in: NSRect(x: 0, y: 0, width: size, height: size), angle: -60)
let glow = NSGradient(colors: [NSColor.white.withAlphaComponent(0.28), NSColor.white.withAlphaComponent(0)])!
glow.draw(fromCenter: NSPoint(x: size * 0.28, y: size * 0.82), radius: 0,
          toCenter: NSPoint(x: size * 0.28, y: size * 0.82), radius: size * 0.75, options: [])

func drawWord(_ text: String, in rect: NSRect, size fontSize: CGFloat, color: NSColor) {
    let style = NSMutableParagraphStyle()
    style.alignment = .center
    let attrs: [NSAttributedString.Key: Any] = [
        .font: roundedFont(fontSize, .heavy), .foregroundColor: color, .paragraphStyle: style,
        .kern: -fontSize * 0.01,
    ]
    let s = NSAttributedString(string: text, attributes: attrs)
    let bounds = s.boundingRect(with: rect.size, options: [.usesLineFragmentOrigin])
    s.draw(in: NSRect(x: rect.minX, y: rect.midY - bounds.height / 2 - fontSize * 0.02,
                      width: rect.width, height: bounds.height))
}

if style == "word" {
    cg.setShadow(offset: CGSize(width: 0, height: -18), blur: 40, color: rgb(0x5A3500, 0.35).cgColor)
    drawWord("לוח", in: NSRect(x: 0, y: 0, width: size, height: size), size: 470, color: paper)
} else {
    // The page: a soft shadow under it, so it sits on the amber rather than in it.
    let page = NSRect(x: size * 0.19, y: size * 0.17, width: size * 0.62, height: size * 0.64)
    let radius = size * 0.085
    cg.saveGState()
    cg.setShadow(offset: CGSize(width: 0, height: -26), blur: 60, color: rgb(0x4A2A00, 0.38).cgColor)
    paper.setFill()
    NSBezierPath(roundedRect: page, xRadius: radius, yRadius: radius).fill()
    cg.restoreGState()

    // Its binding: a band of ink across the top, clipped to the page's corners.
    cg.saveGState()
    NSBezierPath(roundedRect: page, xRadius: radius, yRadius: radius).addClip()
    let band = NSRect(x: page.minX, y: page.maxY - page.height * 0.22, width: page.width, height: page.height * 0.22)
    NSGradient(colors: [rgb(0x2A2318), ink])!.draw(in: band, angle: -90)
    cg.restoreGState()

    // Two rings through the band.
    for x in [page.minX + page.width * 0.28, page.maxX - page.width * 0.28] {
        let ring = NSRect(x: x - size * 0.032, y: page.maxY - size * 0.02, width: size * 0.064, height: size * 0.11)
        rgb(0xF2EDE0).setFill()
        NSBezierPath(roundedRect: ring, xRadius: size * 0.032, yRadius: size * 0.032).fill()
    }

    // The word, on the page below the band.
    let body = NSRect(x: page.minX, y: page.minY + page.height * 0.07, width: page.width, height: page.height * 0.71)
    drawWord("לוח", in: body, size: 300, color: ink)
    // A small amber dot: today.
    rgb(0xE9A12A).setFill()
    NSBezierPath(ovalIn: NSRect(x: page.midX - size * 0.024, y: page.minY + page.height * 0.065,
                                width: size * 0.048, height: size * 0.048)).fill()
}

NSGraphicsContext.restoreGraphicsState()
let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: out) as CFURL, "public.png" as CFString, 1, nil)!
CGImageDestinationAddImage(dest, cg.makeImage()!, nil)
CGImageDestinationFinalize(dest)
print("icon: wrote \(out) (\(style))")
