(function () {
  const form = document.getElementById('salesChatForm');
  if (!form) return;
  const input = document.getElementById('salesChatQuestion');
  const send = document.getElementById('salesChatSend');
  const messages = document.getElementById('salesChatMessages');
  const context = document.getElementById('salesChatContext');
  const prompts = document.getElementById('salesChatPrompts');
  let busy = false;

  function addMessage(role, text, source, scope) {
    const article = document.createElement('div');
    article.className = `sales-chat-message ${role}`;
    const speaker = document.createElement('span');
    speaker.className = 'sales-chat-speaker';
    speaker.textContent = role === 'user' ? 'You' : 'Sales Analyst';
    const paragraph = document.createElement('p');
    paragraph.textContent = text;
    article.append(speaker, paragraph);
    if (scope) {
      const detail = document.createElement('small');
      detail.textContent = `${source || 'Dashboard'} · ${scope}`;
      article.append(detail);
    }
    messages.append(article);
    while (messages.children.length > 30) messages.firstElementChild.remove();
    messages.scrollTop = messages.scrollHeight;
    return article;
  }

  function currentFilters() {
    return typeof window.getDashboardChatFilters === 'function'
      ? window.getDashboardChatFilters() : {};
  }

  function updateContext() {
    const filters = currentFilters();
    const parts = [filters.team, filters.designation, filters.month, filters.period].filter(Boolean);
    context.textContent = parts.length ? parts.join(' · ') : 'Waiting for dashboard data';
  }

  async function ask(question) {
    const trimmed = String(question || '').trim();
    if (!trimmed || busy) return;
    const filters = currentFilters();
    addMessage('user', trimmed);
    input.value = '';
    busy = true;
    send.disabled = true;
    input.disabled = true;
    send.textContent = 'Thinking…';
    const pending = addMessage('assistant', 'Checking dashboard data…');
    try {
      const response = await fetch('/api/sales-chat', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: trimmed, filters })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
      pending.querySelector('p').textContent = data.answer || 'No answer is available for this selection.';
      if (data.scope) {
        const detail = document.createElement('small');
        detail.textContent = `${data.source || 'Dashboard'} · ${data.scope}`;
        pending.append(detail);
      }
      if (data.sql) {
        const details = document.createElement('details');
        details.className = 'sales-chat-query';
        const summary = document.createElement('summary');
        summary.textContent = 'View SQL query';
        const code = document.createElement('pre');
        code.textContent = data.sql;
        details.append(summary, code);
        pending.append(details);
      }
    } catch (error) {
      pending.classList.add('error');
      pending.querySelector('p').textContent = error.message || 'The Sales Analyst could not load an answer. Please try again.';
    } finally {
      busy = false;
      send.disabled = false;
      input.disabled = false;
      send.textContent = 'Send';
      input.focus();
      messages.scrollTop = messages.scrollHeight;
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    ask(input.value);
  });
  prompts.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (button) ask(button.textContent);
  });
  document.addEventListener('dashboard:data-loaded', updateContext);
  updateContext();
})();
