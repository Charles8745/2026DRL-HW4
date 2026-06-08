// Pure helpers for the chat composer. No DOM access — Node-testable.
// Enter submits; Shift+Enter inserts a newline; Enter during IME composition is ignored.
export function isSubmitKey(e) {
  return e.key === 'Enter' && !e.shiftKey && !e.isComposing;
}

// Composer affordance while a turn is streaming: disable the textarea and turn the
// send button into a stop control. Pure — maps a boolean to display state.
export function composerState(isStreaming) {
  return isStreaming
    ? { disabled: true,  sendLabel: '停止', stop: true }
    : { disabled: false, sendLabel: '送出', stop: false };
}
