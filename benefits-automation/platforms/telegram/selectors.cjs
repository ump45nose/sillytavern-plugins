"use strict";
// Every Telegram Web K page assumption lives here. Checked against
// morethanwords/tweb 579e559 (2026-10-16): #auth-pages hosts the login cards
// (CSS-module class names, so only stable ids/tags are used), #column-left
// appears once signed in, bubbles carry data-mid with is-in/is-out. The password
// card (PasswordCard.tsx, passwordInputField.ts, base.scss .stealthy) was
// rechecked against tweb 1da254b (2026-10-19).
const BASE_URL = "https://web.telegram.org/k/";

const SELECTORS = Object.freeze({
  authPages: "#auth-pages",
  // The password card also renders a canvas (the monkey sticker), so a canvas
  // only means QR while no password field is shown.
  qrCanvas: "#auth-pages canvas",
  // PasswordInputHelpers wraps the real field in two decoy password inputs
  // (class "stealthy", aria-hidden, 1px, opacity 0). Playwright counts them as
  // visible and the first one precedes the real field, so they must be excluded.
  passwordInput: '#auth-pages input[type="password"]:not(.stealthy):not([aria-hidden="true"])',
  appColumn: "#column-left",
  messageInput: '.input-message-input[contenteditable="true"]',
  sendButton: ".btn-send",
  startButton: ".chat-input-control-button",
  bubble: ".bubbles-inner .bubble[data-mid]",
  messageText: ".message",
  inlineButton: ".reply-markup-button",
  answers: ".toast, .popup-confirmation",
});

const LIMITS = Object.freeze({messages: 30, text: 4096, buttons: 50, buttonText: 128, answers: 5});

// Runs inside the page (serialized by page.evaluate); keep it self-contained.
// Text is returned only to this process for in-memory matching.
function readPage({selectors, limits}) {
  const visible = (element) => {
    if (!element || element.getClientRects().length === 0) return false;
    const style = getComputedStyle(element);
    return style.visibility !== "hidden" && style.display !== "none" && style.opacity !== "0";
  };
  const all = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const anyVisible = (selector) => all(selector).some(visible);
  const text = (element, limit) =>
    (element ? element.innerText || element.textContent || "" : "").slice(0, limit);
  const authenticated = anyVisible(selectors.appColumn) && !anyVisible(selectors.authPages);
  const input = all(selectors.messageInput).find(visible);
  const messages = all(selectors.bubble)
    .filter((bubble) => !bubble.classList.contains("service"))
    .slice(-limits.messages)
    .map((bubble) => ({
      mid: String(bubble.dataset.mid || ""),
      out: bubble.classList.contains("is-out"),
      text: text(bubble.querySelector(selectors.messageText), limits.text),
      buttons: all(selectors.inlineButton, bubble)
        .slice(0, limits.buttons)
        .map((button) => text(button, limits.buttonText).trim()),
    }));
  const password = all(selectors.passwordInput).find(visible);
  return {
    auth: anyVisible(selectors.authPages),
    authenticated,
    qr: !password && anyVisible(selectors.qrCanvas),
    passwordRequired: Boolean(password),
    // Web K disables the field while checking and marks it .error when rejected.
    passwordBusy: Boolean(password && password.disabled),
    passwordRejected: Boolean(password && !password.disabled && password.classList.contains("error")),
    inputReady: Boolean(input),
    startRequired: !input && anyVisible(selectors.startButton),
    messages,
    answers: all(selectors.answers).filter(visible).slice(0, limits.answers)
      .map((element) => text(element, limits.text)),
  };
}

async function boundedRead(promise) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(Error("telegram_snapshot_timeout")), 10000);
    })]);
  } finally {
    clearTimeout(timer);
  }
}

async function snapshot(page) {
  const value = await boundedRead(page.evaluate(readPage, {selectors: SELECTORS, limits: LIMITS}));
  if (!value || typeof value !== "object" || !Array.isArray(value.messages))
    throw Error("selector_broken");
  return value;
}

const normalize = (value) => String(value).normalize("NFKC").toLowerCase();

function midValue(message) {
  return /^\d{1,20}(?:\.\d{1,12})?$/.test(message.mid) ? Number(message.mid) : null;
}

module.exports = {BASE_URL, SELECTORS, LIMITS, readPage, snapshot, boundedRead, normalize, midValue};
