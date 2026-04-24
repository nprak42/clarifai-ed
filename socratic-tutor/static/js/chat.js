(function () {
  'use strict';

  const messagesEl = document.getElementById('messages');
  const inputBox   = document.getElementById('inputBox');
  const sendBtn    = document.getElementById('sendBtn');
  const resetBtn   = document.getElementById('resetBtn');
  const chatWindow = document.getElementById('chatWindow');

  let isStreaming = false;

  function apiUrl(path) {
    return new URL(`api/${path}`, window.location.href).toString();
  }

  // ----------------------------------------------------------------
  // Scroll
  // ----------------------------------------------------------------
  function scrollToBottom() {
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  // ----------------------------------------------------------------
  // Message rendering
  // ----------------------------------------------------------------
  function addMessage(role, text) {
    const msg = document.createElement('div');
    msg.className = `msg ${role}`;

    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = role === 'tutor' ? 'Tutor' : (STUDENT_NAME || 'You');

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;

    msg.appendChild(label);
    msg.appendChild(bubble);
    messagesEl.appendChild(msg);
    scrollToBottom();
    return bubble;
  }

  function addTypingIndicator() {
    const msg = document.createElement('div');
    msg.className = 'msg tutor';
    msg.id = 'typingMsg';

    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = 'Tutor';

    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.innerHTML = '<span></span><span></span><span></span>';

    msg.appendChild(label);
    msg.appendChild(indicator);
    messagesEl.appendChild(msg);
    scrollToBottom();
    return msg;
  }

  function removeTypingIndicator() {
    const el = document.getElementById('typingMsg');
    if (el) el.remove();
  }

  function showError(text) {
    const msg = document.createElement('div');
    msg.className = 'msg error';
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;
    msg.appendChild(bubble);
    messagesEl.appendChild(msg);
    scrollToBottom();
  }

  // ----------------------------------------------------------------
  // Send message
  // ----------------------------------------------------------------
  async function sendMessage() {
    const text = inputBox.value.trim();
    if (!text || isStreaming) return;

    addMessage('student', text);
    inputBox.value = '';
    inputBox.style.height = 'auto';
    setInputEnabled(false);

    const typingMsg = addTypingIndicator();
    isStreaming = true;

    let tutorBubble = null;
    let fullText = '';

    try {
      const resp = await fetch(apiUrl('chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });

      if (!resp.ok) throw new Error('Server error');

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep incomplete line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let data;
          try { data = JSON.parse(raw); } catch { continue; }

          if (data.error) {
            removeTypingIndicator();
            showError(data.error);
            break;
          }

          if (data.token) {
            if (!tutorBubble) {
              removeTypingIndicator();
              tutorBubble = addMessage('tutor', '');
            }
            fullText += data.token;
            tutorBubble.textContent = fullText;
            scrollToBottom();
          }

          if (data.done) break;
        }
      }
    } catch (err) {
      removeTypingIndicator();
      showError('Something went wrong. Please try again.');
    }

    isStreaming = false;
    setInputEnabled(true);
    inputBox.focus();
  }

  // ----------------------------------------------------------------
  // Input helpers
  // ----------------------------------------------------------------
  function setInputEnabled(enabled) {
    inputBox.disabled = !enabled;
    sendBtn.disabled = !enabled;
    if (enabled) updateSendBtn();
  }

  function updateSendBtn() {
    sendBtn.disabled = inputBox.value.trim().length === 0;
  }

  // Auto-resize textarea
  function autoResize() {
    inputBox.style.height = 'auto';
    inputBox.style.height = Math.min(inputBox.scrollHeight, 120) + 'px';
  }

  // ----------------------------------------------------------------
  // Reset
  // ----------------------------------------------------------------
  async function resetSession() {
    if (!confirm('Start a new session? The conversation will be cleared.')) return;
    await fetch(apiUrl('reset'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    messagesEl.innerHTML = '';
    inputBox.value = '';
    inputBox.style.height = 'auto';
    isStreaming = false;
    setInputEnabled(true);
    loadGreeting();
  }

  // ----------------------------------------------------------------
  // Opening greeting
  // ----------------------------------------------------------------
  async function loadGreeting() {
    const typingMsg = addTypingIndicator();
    try {
      const resp = await fetch(apiUrl('greeting'));
      const data = await resp.json();
      removeTypingIndicator();
      if (data.reply) {
        addMessage('tutor', data.reply);
      }
    } catch {
      removeTypingIndicator();
      addMessage('tutor', `Hi! Let's work on this problem together. What do you think the first step is?`);
    }
  }

  // ----------------------------------------------------------------
  // Event listeners
  // ----------------------------------------------------------------
  sendBtn.addEventListener('click', sendMessage);

  inputBox.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  inputBox.addEventListener('input', function () {
    updateSendBtn();
    autoResize();
  });

  resetBtn.addEventListener('click', resetSession);

  // ----------------------------------------------------------------
  // Init
  // ----------------------------------------------------------------
  loadGreeting();

})();
