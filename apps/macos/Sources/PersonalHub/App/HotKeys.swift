import AppKit
import Carbon.HIToolbox

struct Shortcut: Codable, Equatable {
    var keyCode: UInt32
    /// Carbon modifier mask (controlKey, optionKey, cmdKey, shiftKey).
    var modifiers: UInt32

    static let quickTask = Shortcut(keyCode: UInt32(kVK_Space), modifiers: UInt32(controlKey | optionKey))
    static let quickMemo = Shortcut(keyCode: UInt32(kVK_ANSI_M), modifiers: UInt32(controlKey | optionKey))

    init(keyCode: UInt32, modifiers: UInt32) {
        self.keyCode = keyCode
        self.modifiers = modifiers
    }

    init?(event: NSEvent) {
        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        var m: UInt32 = 0
        if flags.contains(.control) { m |= UInt32(controlKey) }
        if flags.contains(.option) { m |= UInt32(optionKey) }
        if flags.contains(.command) { m |= UInt32(cmdKey) }
        if flags.contains(.shift) { m |= UInt32(shiftKey) }
        // A global shortcut needs at least one of ⌃ ⌥ ⌘ so plain typing is never captured.
        guard m & UInt32(controlKey | optionKey | cmdKey) != 0 else { return nil }
        self.init(keyCode: UInt32(event.keyCode), modifiers: m)
    }

    var display: String {
        var s = ""
        if modifiers & UInt32(controlKey) != 0 { s += "⌃" }
        if modifiers & UInt32(optionKey) != 0 { s += "⌥" }
        if modifiers & UInt32(shiftKey) != 0 { s += "⇧" }
        if modifiers & UInt32(cmdKey) != 0 { s += "⌘" }
        return s + Self.keyName(keyCode)
    }

    static func keyName(_ code: UInt32) -> String {
        switch Int(code) {
        case kVK_Space: return "Space"
        case kVK_Return: return "↩"
        case kVK_Tab: return "⇥"
        case kVK_Escape: return "Esc"
        default: break
        }
        let letters: [Int: String] = [
            kVK_ANSI_A: "A", kVK_ANSI_B: "B", kVK_ANSI_C: "C", kVK_ANSI_D: "D", kVK_ANSI_E: "E", kVK_ANSI_F: "F", kVK_ANSI_G: "G",
            kVK_ANSI_H: "H", kVK_ANSI_I: "I", kVK_ANSI_J: "J", kVK_ANSI_K: "K", kVK_ANSI_L: "L", kVK_ANSI_M: "M", kVK_ANSI_N: "N",
            kVK_ANSI_O: "O", kVK_ANSI_P: "P", kVK_ANSI_Q: "Q", kVK_ANSI_R: "R", kVK_ANSI_S: "S", kVK_ANSI_T: "T", kVK_ANSI_U: "U",
            kVK_ANSI_V: "V", kVK_ANSI_W: "W", kVK_ANSI_X: "X", kVK_ANSI_Y: "Y", kVK_ANSI_Z: "Z",
            kVK_ANSI_0: "0", kVK_ANSI_1: "1", kVK_ANSI_2: "2", kVK_ANSI_3: "3", kVK_ANSI_4: "4",
            kVK_ANSI_5: "5", kVK_ANSI_6: "6", kVK_ANSI_7: "7", kVK_ANSI_8: "8", kVK_ANSI_9: "9",
        ]
        return letters[Int(code)] ?? "#\(code)"
    }
}

/// Global hotkeys via Carbon `RegisterEventHotKey`; works without Accessibility permission.
@MainActor
final class HotKeyCenter {
    static let shared = HotKeyCenter()

    enum Action: UInt32, CaseIterable {
        case quickTask = 1, quickMemo = 2

        var defaultsKey: String { "hotkey.\(self)" }
        var fallback: Shortcut { self == .quickTask ? .quickTask : .quickMemo }
        var title: String { self == .quickTask ? "快速任务" : "快速 Memo" }
    }

    private var refs: [UInt32: EventHotKeyRef] = [:]
    private var handlers: [UInt32: () -> Void] = [:]
    private var installed = false

    func shortcut(for action: Action) -> Shortcut {
        guard let data = UserDefaults.standard.data(forKey: action.defaultsKey),
              let s = try? JSONDecoder().decode(Shortcut.self, from: data) else { return action.fallback }
        return s
    }

    @discardableResult
    func set(_ shortcut: Shortcut, for action: Action) -> Bool {
        let previous = self.shortcut(for: action)
        unregister(action)
        guard register(shortcut, id: action.rawValue) else {
            register(previous, id: action.rawValue)
            return false
        }
        UserDefaults.standard.set(try? JSONEncoder().encode(shortcut), forKey: action.defaultsKey)
        return true
    }

    func bind(_ action: Action, handler: @escaping () -> Void) {
        installHandler()
        handlers[action.rawValue] = handler
        register(shortcut(for: action), id: action.rawValue)
    }

    func suspend() { Action.allCases.forEach(unregister) }

    func resume() { Action.allCases.forEach { register(shortcut(for: $0), id: $0.rawValue) } }

    private func unregister(_ action: Action) {
        if let ref = refs.removeValue(forKey: action.rawValue) { UnregisterEventHotKey(ref) }
    }

    @discardableResult
    private func register(_ s: Shortcut, id: UInt32) -> Bool {
        guard refs[id] == nil else { return true }
        var ref: EventHotKeyRef?
        let hotKeyID = EventHotKeyID(signature: OSType(0x5048_5542), id: id) // "PHUB"
        let status = RegisterEventHotKey(s.keyCode, s.modifiers, hotKeyID, GetApplicationEventTarget(), 0, &ref)
        guard status == noErr, let ref else {
            NSLog("Personal Hub: hotkey \(s.display) unavailable (\(status))")
            return false
        }
        refs[id] = ref
        return true
    }

    fileprivate func fire(_ id: UInt32) { handlers[id]?() }

    private func installHandler() {
        guard !installed else { return }
        installed = true
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, event, _ in
            var hk = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                              MemoryLayout<EventHotKeyID>.size, nil, &hk)
            let id = hk.id
            DispatchQueue.main.async { MainActor.assumeIsolated { HotKeyCenter.shared.fire(id) } }
            return noErr
        }, 1, &spec, nil, nil)
    }
}
