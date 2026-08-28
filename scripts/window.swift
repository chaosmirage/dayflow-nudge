// DayflowNudgeWindow: the styled nudge surface.
//
// A small borderless, non-activating panel centered on the screen: a dark
// rounded card in the Dayflow visual style (Figtree when present, soft
// whites, the Dayflow yellow accent). The payload arrives through the same
// DFN_* environment variables as the notification applet, because that is
// the one transport that survives a direct binary launch. The card fades
// in, shows a shrinking progress line, and closes itself after the give-up
// window; the button closes it early. The panel never takes keyboard
// focus, so it interrupts without derailing typing.

import AppKit
import SwiftUI

let GIVE_UP_SECONDS: TimeInterval = 30
let CARD_WIDTH: CGFloat = 440

struct CardView: View {
  let title: String
  let drift: String
  let onClose: () -> Void

  @State private var opacity: Double = 0
  @State private var progress: CGFloat = 1

  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      Text(title)
        .font(.custom("Figtree", size: 21).weight(.bold))
        .foregroundStyle(.white)
        .lineLimit(2)

      Text(drift)
        .font(.custom("Figtree", size: 15))
        .foregroundStyle(.white.opacity(0.72))
        .lineLimit(3)

      GeometryReader { proxy in
        ZStack(alignment: .leading) {
          Capsule().fill(.white.opacity(0.10))
          Capsule()
            .fill(Color(red: 1.0, green: 0.84, blue: 0.35))
            .frame(width: max(proxy.size.width * progress, 8))
        }
      }
      .frame(height: 4)

      HStack {
        Spacer()
        Button(action: onClose) {
          Text("Back to work")
            .font(.custom("Figtree", size: 14).weight(.semibold))
            .foregroundStyle(.black)
            .padding(.horizontal, 18)
            .padding(.vertical, 9)
            .background(
              Capsule().fill(Color(red: 1.0, green: 0.84, blue: 0.35)))
        }
        .buttonStyle(.plain)
      }
    }
    .padding(26)
    .frame(width: CARD_WIDTH)
    .background(
      RoundedRectangle(cornerRadius: 24).fill(.black.opacity(0.88)))
    .overlay(
      RoundedRectangle(cornerRadius: 24).strokeBorder(.white.opacity(0.08)))
    .opacity(opacity)
    .onAppear {
      withAnimation(.easeOut(duration: 0.22)) { opacity = 1 }
      withAnimation(.linear(duration: GIVE_UP_SECONDS)) { progress = 0.02 }
    }
  }
}

final class PanelDelegate: NSObject, NSApplicationDelegate {
  var panel: NSPanel?

  func applicationDidFinishLaunching(_ note: Notification) {
    let env = ProcessInfo.processInfo.environment
    let title = env["DFN_TITLE"] ?? "DayflowNudge"
    let drift = env["DFN_BODY"] ?? ""

    let panel = NSPanel(
      contentRect: NSRect(x: 0, y: 0, width: CARD_WIDTH, height: 190),
      styleMask: [.borderless, .nonactivatingPanel],
      backing: .buffered, defer: false)
    panel.isFloatingPanel = true
    panel.isOpaque = false
    panel.backgroundColor = .clear
    panel.hasShadow = true
    panel.level = .floating
    panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
    panel.animationBehavior = .utilityWindow

    let close = { [weak panel] in
      NSAnimationContext.runAnimationGroup { context in
        context.duration = 0.18
        panel?.animator().alphaValue = 0
      } completionHandler: {
        panel?.orderOut(nil)
        NSApp.terminate(nil)
      }
    }
    let host = NSHostingView(
      rootView: CardView(
        title: title, drift: drift, onClose: close))
    host.frame = panel.contentRect(forFrameRect: panel.frame)
    panel.contentView = host
    panel.center()
    panel.alphaValue = 0
    panel.orderFrontRegardless()
    NSAnimationContext.runAnimationGroup { context in
      context.duration = 0.22
      panel.animator().alphaValue = 1
    }

    if env["DFN_SOUND"] == "sound" {
      NSSound(named: "Glass")?.play()
    } else {
      NSSound(named: "Submarine")?.play()
    }

    self.panel = panel
    DispatchQueue.main.asyncAfter(deadline: .now() + GIVE_UP_SECONDS) {
      close()
    }
  }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = PanelDelegate()
app.delegate = delegate
app.run()
