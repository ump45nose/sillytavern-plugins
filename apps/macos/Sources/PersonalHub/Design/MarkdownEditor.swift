import AppKit
import HubKit
import SwiftUI

/// Plain Markdown text that shows its rendered style while you type: headings, emphasis, lists,
/// checkboxes, quotes, code and links. Syntax markers stay in the text, dimmed.
struct MarkdownEditor: NSViewRepresentable {
    @Binding var text: String
    var editable = true
    var size: CGFloat = 13.5
    var inset = NSSize(width: 16, height: 14)

    func makeCoordinator() -> Coordinator { Coordinator(text: $text, style: MarkdownStyle(size: size)) }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSTextView.scrollableTextView()
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        HubScroller.adopt(scroll)
        guard let view = scroll.documentView as? NSTextView else { return scroll }
        view.delegate = context.coordinator
        view.drawsBackground = false
        view.isRichText = false
        view.isEditable = editable
        view.allowsUndo = true
        view.isAutomaticQuoteSubstitutionEnabled = false
        view.isAutomaticDashSubstitutionEnabled = false
        view.isAutomaticTextReplacementEnabled = false
        view.isAutomaticSpellingCorrectionEnabled = false
        view.textContainerInset = inset
        view.insertionPointColor = NSColor(Tone.clay.color)
        view.selectedTextAttributes = [.backgroundColor: NSColor(Tone.clay.tint)]
        view.string = text
        context.coordinator.style.apply(to: view)
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        context.coordinator.text = $text
        guard let view = scroll.documentView as? NSTextView else { return }
        view.isEditable = editable
        guard view.string != text else { return }
        view.string = text
        context.coordinator.style.apply(to: view)
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var text: Binding<String>
        let style: MarkdownStyle
        init(text: Binding<String>, style: MarkdownStyle) { self.text = text; self.style = style }

        func textDidChange(_ note: Notification) {
            guard let view = note.object as? NSTextView else { return }
            text.wrappedValue = view.string
            style.apply(to: view)
        }

        /// Return on a list line continues the list; on an empty item it ends the list.
        func textView(_ view: NSTextView, doCommandBy selector: Selector) -> Bool {
            guard selector == #selector(NSResponder.insertNewline(_:)) else { return false }
            let ns = view.string as NSString, caret = view.selectedRange().location
            let line = ns.lineRange(for: NSRange(location: caret, length: 0))
            let current = ns.substring(with: line).trimmingCharacters(in: .newlines)
            guard let marker = MarkdownStyle.continuation(of: current) else { return false }
            if current.trimmingCharacters(in: .whitespaces) == marker.trimmingCharacters(in: .whitespaces) {
                view.insertText("", replacementRange: NSRange(location: line.location, length: (current as NSString).length))
                return true
            }
            view.insertText("\n" + marker, replacementRange: view.selectedRange())
            return true
        }
    }
}

/// Attributes for one Markdown document; restyling is line by line and cheap for review-sized text.
struct MarkdownStyle {
    var size: CGFloat

    private var body: NSFont { .systemFont(ofSize: size) }
    private var bold: NSFont { .systemFont(ofSize: size, weight: .semibold) }
    private var mono: NSFont { .monospacedSystemFont(ofSize: size - 1, weight: .regular) }

    private func paragraph(indent: CGFloat = 0, before: CGFloat = 0, spacing: CGFloat = 5) -> NSParagraphStyle {
        let p = NSMutableParagraphStyle()
        p.lineSpacing = spacing
        p.paragraphSpacing = 3
        p.paragraphSpacingBefore = before
        p.headIndent = indent
        return p
    }

    private static let heading = try! NSRegularExpression(pattern: "^(#{1,6})\\s+")
    private static let list = try! NSRegularExpression(pattern: "^(\\s*)([-*+]|\\d+[.)])\\s+(\\[[ xX]\\]\\s+)?")
    private static let quote = try! NSRegularExpression(pattern: "^\\s*>\\s?")
    private static let rule = try! NSRegularExpression(pattern: "^\\s*([-*_])(\\s*\\1){2,}\\s*$")
    private static let inline: [(NSRegularExpression, Inline)] = [
        (try! NSRegularExpression(pattern: "`([^`\\n]+)`"), .code),
        (try! NSRegularExpression(pattern: "\\*\\*([^*\\n]+)\\*\\*"), .bold),
        (try! NSRegularExpression(pattern: "(?<![*\\w])\\*([^*\\s][^*\\n]*?)\\*(?!\\*)"), .italic),
        (try! NSRegularExpression(pattern: "~~([^~\\n]+)~~"), .strike),
        (try! NSRegularExpression(pattern: "\\[([^\\]\\n]+)\\]\\(([^)\\s]+)\\)"), .link),
    ]
    private enum Inline { case code, bold, italic, strike, link }

    static func continuation(of line: String) -> String? {
        let ns = line as NSString
        guard let m = list.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) else { return nil }
        let indent = ns.substring(with: m.range(at: 1)), marker = ns.substring(with: m.range(at: 2))
        let next = Int(marker.dropLast()).map { "\($0 + 1)\(marker.last!)" } ?? marker
        return indent + next + " " + (m.range(at: 3).location == NSNotFound ? "" : "[ ] ")
    }

    func apply(to view: NSTextView) {
        guard let storage = view.textStorage else { return }
        let ink = NSColor(Palette.ink), ink2 = NSColor(Palette.ink2), ink3 = NSColor(Palette.ink3), faint = NSColor(Palette.ink4)
        let base: [NSAttributedString.Key: Any] = [.font: body, .foregroundColor: ink, .paragraphStyle: paragraph()]
        let ns = storage.string as NSString
        storage.beginEditing()
        storage.setAttributes(base, range: NSRange(location: 0, length: ns.length))
        ns.enumerateSubstrings(in: NSRange(location: 0, length: ns.length), options: [.byLines, .substringNotRequired]) { _, range, _, _ in
            let line = ns.substring(with: range), local = NSRange(location: 0, length: range.length)
            func at(_ r: NSRange) -> NSRange { NSRange(location: range.location + r.location, length: r.length) }
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if let m = Self.heading.firstMatch(in: line, range: local) {
                let level = m.range(at: 1).length
                let font: NSFont = switch level {
                case 1: Typo.serifFont(size + 9)
                case 2: Typo.serifFont(size + 5)
                case 3: .systemFont(ofSize: size + 1.5, weight: .semibold)
                default: bold
                }
                storage.addAttributes([.font: font, .paragraphStyle: paragraph(before: level <= 2 ? 10 : 6, spacing: 3)], range: range)
                storage.addAttributes([.foregroundColor: faint, .font: NSFont.systemFont(ofSize: size - 1)], range: at(m.range))
                return
            }
            if Self.rule.firstMatch(in: line, range: local) != nil {
                storage.addAttributes([.foregroundColor: faint], range: range)
                return
            }
            if let m = Self.quote.firstMatch(in: line, range: local) {
                storage.addAttributes([.foregroundColor: ink2, .paragraphStyle: paragraph(indent: 14)], range: range)
                storage.addAttributes([.foregroundColor: NSColor(Tone.clay.color).withAlphaComponent(0.7), .font: bold], range: at(m.range))
            } else if let m = Self.list.firstMatch(in: line, range: local) {
                let markerWidth = (ns.substring(with: at(m.range)) as NSString).size(withAttributes: [.font: body]).width
                storage.addAttributes([.paragraphStyle: paragraph(indent: markerWidth)], range: range)
                storage.addAttributes([.foregroundColor: NSColor(Tone.clay.color)], range: at(m.range(at: 2)))
                if m.range(at: 3).location != NSNotFound {
                    let box = at(m.range(at: 3)), done = ns.substring(with: box).lowercased().contains("x")
                    storage.addAttributes([.foregroundColor: done ? NSColor(Tone.olive.color) : ink3, .font: NSFont.monospacedSystemFont(ofSize: size - 1, weight: .semibold)], range: box)
                    if done {
                        let rest = NSRange(location: NSMaxRange(box), length: NSMaxRange(range) - NSMaxRange(box))
                        storage.addAttributes([.foregroundColor: ink3, .strikethroughStyle: NSUnderlineStyle.single.rawValue], range: rest)
                    }
                } else if let colon = line.firstIndex(where: { $0 == "：" || $0 == ":" }), line.distance(from: line.startIndex, to: colon) < 16 {
                    let end = line.distance(from: line.startIndex, to: colon) + 1
                    let label = NSRange(location: NSMaxRange(m.range), length: max(0, (String(line.prefix(end)) as NSString).length - NSMaxRange(m.range)))
                    storage.addAttributes([.foregroundColor: ink2], range: at(label))
                }
            } else if trimmed.hasSuffix("：") || trimmed.hasSuffix(":") {
                storage.addAttributes([.font: bold, .paragraphStyle: paragraph(before: 6)], range: range)
            }

            for (regex, kind) in Self.inline {
                for m in regex.matches(in: line, range: local) {
                    let whole = at(m.range), inner = at(m.range(at: 1))
                    switch kind {
                    case .code:
                        storage.addAttributes([.font: mono, .backgroundColor: NSColor(Palette.sunk), .foregroundColor: NSColor(Tone.clay.color)], range: inner)
                    case .bold:
                        storage.addAttributes([.font: bold], range: inner)
                    case .italic:
                        storage.addAttributes([.obliqueness: 0.15], range: inner)
                    case .strike:
                        storage.addAttributes([.strikethroughStyle: NSUnderlineStyle.single.rawValue, .foregroundColor: ink3], range: inner)
                    case .link:
                        storage.addAttributes([.foregroundColor: NSColor(Tone.sky.color)], range: inner)
                        storage.addAttributes([.foregroundColor: faint, .font: NSFont.systemFont(ofSize: size - 2)], range: at(m.range(at: 2)))
                    }
                    for marker in Self.markers(whole: whole, inner: inner) where marker.length > 0 {
                        storage.addAttributes([.foregroundColor: faint], range: marker)
                    }
                }
            }
        }
        storage.endEditing()
        view.typingAttributes = base
    }

    private static func markers(whole: NSRange, inner: NSRange) -> [NSRange] {
        [NSRange(location: whole.location, length: inner.location - whole.location),
         NSRange(location: NSMaxRange(inner), length: NSMaxRange(whole) - NSMaxRange(inner))]
    }
}
