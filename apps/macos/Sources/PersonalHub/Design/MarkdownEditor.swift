import AppKit
import HubKit
import SwiftUI

/// Plain Markdown text shown typeset while you type: headings, emphasis, lists, checkboxes, quotes,
/// code, links and tags. Syntax markers are hidden except on the lines holding the caret, where they
/// come back so they can be edited; bullets, checkboxes, quote bars and rules are drawn in their place.
struct MarkdownEditor: NSViewRepresentable {
    @Binding var text: String
    var editable = true
    var size: CGFloat = 13.5
    var inset = NSSize(width: 16, height: 14)
    /// Toolbar commands and focus.
    var controller: MarkdownController? = nil
    /// Height of the laid-out text including the inset, for editors that grow with their content.
    var onHeight: ((CGFloat) -> Void)? = nil
    var onEscape: (() -> Void)? = nil
    /// Pasted or dropped files and images; return true when taken, false to paste as text.
    var onFiles: ((NSPasteboard) -> Bool)? = nil

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let storage = NSTextStorage()
        let layout = NSLayoutManager()
        storage.addLayoutManager(layout)
        let container = NSTextContainer(size: NSSize(width: 0, height: CGFloat.greatestFiniteMagnitude))
        container.widthTracksTextView = true
        layout.addTextContainer(container)
        let view = MarkdownTextView(frame: .zero, textContainer: container)
        view.size = size
        view.minSize = .zero
        view.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: .greatestFiniteMagnitude)
        view.isVerticallyResizable = true
        view.isHorizontallyResizable = false
        view.autoresizingMask = [.width]

        let scroll = NSScrollView()
        scroll.documentView = view
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        HubScroller.adopt(scroll)

        let coordinator = context.coordinator
        view.delegate = coordinator
        view.onFocus = { [weak coordinator, weak view] in if let view { coordinator?.restyle(view) } }
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
        view.onFiles = onFiles
        controller?.view = view
        coordinator.restyle(view)
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        context.coordinator.parent = self
        guard let view = scroll.documentView as? MarkdownTextView else { return }
        controller?.view = view
        view.onFiles = onFiles
        view.isEditable = editable
        guard view.string != text else { return }
        view.string = text
        context.coordinator.restyle(view)
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: MarkdownEditor
        let style: MarkdownStyle
        private var revealed: NSRange?
        private var height: CGFloat = 0

        init(_ parent: MarkdownEditor) {
            self.parent = parent
            style = MarkdownStyle(size: parent.size)
        }

        /// Skipped while an input method is composing: restyling would drop its marked text.
        func restyle(_ view: NSTextView) {
            guard !view.hasMarkedText() else { return }
            revealed = Self.caretLines(view)
            style.apply(to: view, reveal: revealed)
            report(view)
        }

        func textDidChange(_ note: Notification) {
            guard let view = note.object as? NSTextView else { return }
            parent.text = view.string
            restyle(view)
        }

        func textViewDidChangeSelection(_ note: Notification) {
            guard let view = note.object as? NSTextView, Self.caretLines(view) != revealed else { return }
            restyle(view)
        }

        /// Return on a list line continues the list; on an empty item it ends the list.
        func textView(_ view: NSTextView, doCommandBy selector: Selector) -> Bool {
            if selector == #selector(NSResponder.cancelOperation(_:)), let escape = parent.onEscape {
                escape()
                return true
            }
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

        private func report(_ view: NSTextView) {
            guard parent.onHeight != nil, let layout = view.layoutManager, let container = view.textContainer else { return }
            layout.ensureLayout(for: container)
            let h = ceil(layout.usedRect(for: container).height + view.textContainerInset.height * 2)
            guard abs(h - height) > 0.5 else { return }
            height = h
            DispatchQueue.main.async { [parent] in parent.onHeight?(h) }
        }

        /// The whole lines touched by the selection, while the view is being edited.
        static func caretLines(_ view: NSTextView) -> NSRange? {
            guard view.isEditable, view.window?.firstResponder === view else { return nil }
            return (view.string as NSString).lineRange(for: view.selectedRange())
        }
    }
}

/// Lets toolbars outside the text view format the selection and move focus into it.
@MainActor
final class MarkdownController {
    weak var view: NSTextView?

    func focus() {
        guard let view else { return }
        view.window?.makeFirstResponder(view)
    }

    /// Wraps the selection, or a selected placeholder when nothing is selected.
    func wrap(_ left: String, _ right: String, placeholder: String) {
        guard let view else { return }
        let r = view.selectedRange()
        let inner = r.length > 0 ? (view.string as NSString).substring(with: r) : placeholder
        replace(r, with: left + inner + right, select: NSRange(location: r.location + (left as NSString).length, length: (inner as NSString).length))
    }

    /// Adds the marker to the start of the caret's line, or takes it away when it is already there.
    func toggleLine(_ marker: String) {
        guard let view else { return }
        let ns = view.string as NSString
        let line = ns.lineRange(for: NSRange(location: view.selectedRange().location, length: 0))
        let caret = view.selectedRange().location, length = (marker as NSString).length
        if ns.substring(with: line).hasPrefix(marker) {
            replace(NSRange(location: line.location, length: length), with: "", select: NSRange(location: max(line.location, caret - length), length: 0))
        } else {
            replace(NSRange(location: line.location, length: 0), with: marker, select: NSRange(location: caret + length, length: 0))
        }
    }

    func insert(_ s: String) {
        guard let view else { return }
        let r = view.selectedRange()
        replace(r, with: s, select: NSRange(location: r.location + (s as NSString).length, length: 0))
    }

    private func replace(_ range: NSRange, with s: String, select: NSRange) {
        guard let view, view.shouldChangeText(in: range, replacementString: s) else { return }
        view.textStorage?.replaceCharacters(in: range, with: s)
        view.didChangeText()
        focus()
        view.setSelectedRange(select)
    }
}

extension NSAttributedString.Key {
    /// What to draw over a hidden marker: `bullet`, `box`, `boxDone`, `quote` or `rule`.
    static let markdownMark = NSAttributedString.Key("hub.markdownMark")
    /// Width of the leading whitespace before a list marker.
    static let markdownIndent = NSAttributedString.Key("hub.markdownIndent")
}

/// Draws the marks that stand in for hidden list, quote and rule markers; a click on a checkbox toggles it.
final class MarkdownTextView: NSTextView {
    var size: CGFloat = 13.5
    var onFocus: (() -> Void)?
    var onFiles: ((NSPasteboard) -> Bool)?

    override func paste(_ sender: Any?) {
        if let onFiles, onFiles(.general) { return }
        super.paste(sender)
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        Self.carriesFiles(sender.draggingPasteboard) && onFiles != nil ? .copy : super.draggingEntered(sender)
    }

    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        Self.carriesFiles(sender.draggingPasteboard) && onFiles != nil ? .copy : super.draggingUpdated(sender)
    }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        if Self.carriesFiles(sender.draggingPasteboard), let onFiles, onFiles(sender.draggingPasteboard) { return true }
        return super.performDragOperation(sender)
    }

    private static func carriesFiles(_ pb: NSPasteboard) -> Bool {
        pb.canReadObject(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true])
            || pb.availableType(from: [.png, .tiff]) != nil
    }

    override func becomeFirstResponder() -> Bool {
        let ok = super.becomeFirstResponder()
        if ok { DispatchQueue.main.async { [weak self] in self?.onFocus?() } }
        return ok
    }

    override func resignFirstResponder() -> Bool {
        let ok = super.resignFirstResponder()
        if ok { DispatchQueue.main.async { [weak self] in self?.onFocus?() } }
        return ok
    }

    override func draw(_ dirty: NSRect) {
        super.draw(dirty)
        marks(in: dirty) { kind, range, rect, baseline in
            switch kind {
            case "bullet":
                let d = size * 0.3
                NSColor(Tone.clay.color).setFill()
                NSBezierPath(ovalIn: NSRect(x: rect.minX + 3, y: baseline - size * 0.36 - d / 2, width: d, height: d)).fill()
            case "box", "boxDone":
                let box = checkbox(rect, baseline)
                let path = NSBezierPath(roundedRect: box, xRadius: 3, yRadius: 3)
                if kind == "boxDone" {
                    NSColor(Tone.olive.color).setFill()
                    path.fill()
                    let tick = NSBezierPath()
                    tick.move(to: NSPoint(x: box.minX + box.width * 0.24, y: box.midY))
                    tick.line(to: NSPoint(x: box.minX + box.width * 0.43, y: box.maxY - box.height * 0.27))
                    tick.line(to: NSPoint(x: box.maxX - box.width * 0.22, y: box.minY + box.height * 0.27))
                    tick.lineWidth = 1.6
                    tick.lineCapStyle = .round
                    tick.lineJoinStyle = .round
                    NSColor.white.setStroke()
                    tick.stroke()
                } else {
                    NSColor(Palette.ink3).setStroke()
                    path.lineWidth = 1.2
                    path.stroke()
                }
            case "quote":
                guard let layout = layoutManager, let container = textContainer else { return }
                let para = (string as NSString).paragraphRange(for: range)
                let glyphs = layout.glyphRange(forCharacterRange: para, actualCharacterRange: nil)
                let box = layout.boundingRect(forGlyphRange: glyphs, in: container)
                NSColor(Tone.clay.color).withAlphaComponent(0.55).setFill()
                NSBezierPath(roundedRect: NSRect(x: rect.minX + 2, y: box.minY + textContainerOrigin.y + 2, width: 3, height: max(box.height - 8, 10)),
                             xRadius: 1.5, yRadius: 1.5).fill()
            case "rule":
                NSColor(Palette.line).setFill()
                NSRect(x: rect.minX, y: baseline - size * 0.35, width: bounds.width - rect.minX - textContainerInset.width - 5, height: 1).fill()
            default:
                break
            }
        }
    }

    override func mouseDown(with event: NSEvent) {
        let p = convert(event.locationInWindow, from: nil)
        var toggled = false
        if isEditable {
            marks(in: visibleRect) { kind, range, rect, baseline in
                guard !toggled, kind == "box" || kind == "boxDone", checkbox(rect, baseline).insetBy(dx: -4, dy: -4).contains(p) else { return }
                let ns = string as NSString
                let open = ns.range(of: "[", range: range)
                guard open.location != NSNotFound, NSMaxRange(open) < NSMaxRange(range) else { return }
                let mark = NSRange(location: NSMaxRange(open), length: 1), value = kind == "box" ? "x" : " "
                if shouldChangeText(in: mark, replacementString: value) {
                    textStorage?.replaceCharacters(in: mark, with: value)
                    didChangeText()
                }
                toggled = true
            }
        }
        if !toggled { super.mouseDown(with: event) }
    }

    private func checkbox(_ rect: NSRect, _ baseline: CGFloat) -> NSRect {
        let s = (size * 0.92).rounded()
        return NSRect(x: rect.minX + 1, y: baseline - s + 1.5, width: s, height: s)
    }

    /// Each mark in the rect, with its leading edge (after any list indent) and the line's baseline, in view coordinates.
    private func marks(in rect: NSRect, _ body: (String, NSRange, NSRect, CGFloat) -> Void) {
        guard let layout = layoutManager, let container = textContainer, let storage = textStorage, storage.length > 0 else { return }
        let origin = textContainerOrigin
        let glyphs = layout.glyphRange(forBoundingRect: rect.offsetBy(dx: -origin.x, dy: -origin.y), in: container)
        let chars = layout.characterRange(forGlyphRange: glyphs, actualGlyphRange: nil)
        storage.enumerateAttribute(.markdownMark, in: chars) { value, range, _ in
            guard let kind = value as? String else { return }
            let glyph = layout.glyphIndexForCharacter(at: range.location)
            let frag = layout.lineFragmentRect(forGlyphAt: glyph, effectiveRange: nil)
            let baseline = origin.y + frag.minY + layout.location(forGlyphAt: glyph).y
            let indent = (storage.attribute(.markdownIndent, at: range.location, effectiveRange: nil) as? NSNumber).map { CGFloat($0.doubleValue) } ?? 0
            let x = origin.x + frag.minX + container.lineFragmentPadding + indent
            body(kind, range, NSRect(x: x, y: origin.y + frag.minY, width: frag.width, height: frag.height), baseline)
        }
    }
}

/// Attributes for one Markdown document; restyling is line by line and cheap for memo- and review-sized text.
struct MarkdownStyle {
    var size: CGFloat

    private var body: NSFont { .systemFont(ofSize: size) }
    private var bold: NSFont { .systemFont(ofSize: size, weight: .semibold) }
    private var mono: NSFont { .monospacedSystemFont(ofSize: size - 1, weight: .regular) }
    private static let hidden: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 0.01), .foregroundColor: NSColor.clear]

    private func paragraph(indent: CGFloat = 0, first: CGFloat = 0, before: CGFloat = 0, spacing: CGFloat = 5) -> NSParagraphStyle {
        let p = NSMutableParagraphStyle()
        p.lineSpacing = spacing
        p.paragraphSpacing = 3
        p.paragraphSpacingBefore = before
        p.headIndent = indent
        p.firstLineHeadIndent = first
        return p
    }

    private static let heading = try! NSRegularExpression(pattern: "^(#{1,6})\\s+")
    private static let list = try! NSRegularExpression(pattern: "^(\\s*)([-*+]|\\d+[.)])\\s+(\\[[ xX]\\]\\s+)?")
    private static let quote = try! NSRegularExpression(pattern: "^\\s*>\\s?")
    private static let rule = try! NSRegularExpression(pattern: "^\\s*([-*_])(\\s*\\1){2,}\\s*$")
    private static let tag = try! NSRegularExpression(pattern: "(?<![\\w/#&])#[^\\s#]+")
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

    /// Lines intersecting `reveal` keep their markers visible (dimmed); everywhere else they are hidden.
    func apply(to view: NSTextView, reveal: NSRange? = nil) {
        guard let storage = view.textStorage else { return }
        let ink = NSColor(Palette.ink), ink2 = NSColor(Palette.ink2), ink3 = NSColor(Palette.ink3), faint = NSColor(Palette.ink4)
        let base: [NSAttributedString.Key: Any] = [.font: body, .foregroundColor: ink, .paragraphStyle: paragraph()]
        let ns = storage.string as NSString
        storage.beginEditing()
        storage.setAttributes(base, range: NSRange(location: 0, length: ns.length))
        ns.enumerateSubstrings(in: NSRange(location: 0, length: ns.length), options: [.byLines, .substringNotRequired]) { _, range, _, _ in
            let line = ns.substring(with: range), local = NSRange(location: 0, length: range.length)
            func at(_ r: NSRange) -> NSRange { NSRange(location: range.location + r.location, length: r.length) }
            let shown = reveal.map { r in
                (r.location <= range.location && range.location < NSMaxRange(r)) || (range.length == 0 && range.location == r.location)
            } ?? false
            func marker(_ r: NSRange, _ dim: [NSAttributedString.Key: Any]) {
                guard r.length > 0 else { return }
                storage.addAttributes(shown ? dim : Self.hidden, range: r)
            }
            func width(_ s: String) -> CGFloat { (s as NSString).size(withAttributes: [.font: body]).width }
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
                marker(at(m.range), [.foregroundColor: faint, .font: NSFont.systemFont(ofSize: size - 1)])
                inlines(storage, line: line, range: range, shown: shown)
                return
            }
            if Self.rule.firstMatch(in: line, range: local) != nil {
                storage.addAttributes(shown ? [.foregroundColor: faint] : [.foregroundColor: NSColor.clear, .markdownMark: "rule"], range: range)
                return
            }
            if let m = Self.quote.firstMatch(in: line, range: local) {
                let w = width(ns.substring(with: at(m.range)))
                storage.addAttributes([.foregroundColor: ink2, .paragraphStyle: paragraph(indent: 14, first: shown ? max(0, 14 - w) : 14)], range: range)
                marker(at(m.range), [.foregroundColor: NSColor(Tone.clay.color).withAlphaComponent(0.7), .font: bold])
                if !shown { storage.addAttribute(.markdownMark, value: "quote", range: at(m.range)) }
            } else if let m = Self.list.firstMatch(in: line, range: local) {
                let marked = width(ns.substring(with: at(m.range))), indent = width(ns.substring(with: at(m.range(at: 1))))
                let ordered = ns.substring(with: at(m.range(at: 2))).first?.isNumber ?? false
                let boxed = m.range(at: 3).location != NSNotFound
                let full = ordered && !boxed ? marked : indent + (boxed ? (size * 0.92).rounded() + 9 : 15)
                storage.addAttributes([.paragraphStyle: paragraph(indent: full, first: ordered && !boxed ? 0 : shown ? max(0, full - marked) : full)], range: range)
                if ordered && !boxed {
                    storage.addAttributes([.foregroundColor: NSColor(Tone.clay.color)], range: at(m.range(at: 2)))
                } else if shown {
                    storage.addAttributes([.foregroundColor: NSColor(Tone.clay.color)], range: at(m.range(at: 2)))
                } else {
                    let done = boxed && ns.substring(with: at(m.range(at: 3))).lowercased().contains("x")
                    storage.addAttributes(Self.hidden.merging([.markdownMark: boxed ? (done ? "boxDone" : "box") : "bullet",
                                                               .markdownIndent: NSNumber(value: Double(indent))]) { $1 }, range: at(m.range))
                }
                if boxed {
                    let box = at(m.range(at: 3)), done = ns.substring(with: box).lowercased().contains("x")
                    if shown {
                        storage.addAttributes([.foregroundColor: done ? NSColor(Tone.olive.color) : ink3,
                                               .font: NSFont.monospacedSystemFont(ofSize: size - 1, weight: .semibold)], range: box)
                    }
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
            inlines(storage, line: line, range: range, shown: shown)
        }
        storage.endEditing()
        view.typingAttributes = base
        view.needsDisplay = true
    }

    private func inlines(_ storage: NSTextStorage, line: String, range: NSRange, shown: Bool) {
        let local = NSRange(location: 0, length: range.length), faint = NSColor(Palette.ink4)
        func at(_ r: NSRange) -> NSRange { NSRange(location: range.location + r.location, length: r.length) }
        for m in Self.tag.matches(in: line, range: local) {
            storage.addAttributes([.foregroundColor: NSColor(Tone.sky.color)], range: at(m.range))
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
                    storage.addAttributes([.strikethroughStyle: NSUnderlineStyle.single.rawValue, .foregroundColor: NSColor(Palette.ink3)], range: inner)
                case .link:
                    storage.addAttributes([.foregroundColor: NSColor(Tone.sky.color)], range: inner)
                    if !shown { storage.addAttributes([.underlineStyle: NSUnderlineStyle.single.rawValue], range: inner) }
                }
                for marker in Self.markers(whole: whole, inner: inner) where marker.length > 0 {
                    storage.addAttributes(shown ? [.foregroundColor: faint] : Self.hidden, range: marker)
                }
                if kind == .link, shown {
                    storage.addAttributes([.foregroundColor: faint, .font: NSFont.systemFont(ofSize: size - 2)], range: at(m.range(at: 2)))
                }
            }
        }
    }

    private static func markers(whole: NSRange, inner: NSRange) -> [NSRange] {
        [NSRange(location: whole.location, length: inner.location - whole.location),
         NSRange(location: NSMaxRange(inner), length: NSMaxRange(whole) - NSMaxRange(inner))]
    }
}
