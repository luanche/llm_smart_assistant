/**
 * AI Chat Panel - LLM Smart Assistant
 * Uses fixed positioning to fill the content area next to the sidebar.
 * Fetches the chat panel HTML with the HA auth token and loads it via srcdoc
 * so the chat_panel endpoint can require authentication (review requirement).
 */
class LLMChatPanel extends HTMLElement {
  async connectedCallback() {
    // Get HA auth token (window.hassConnection is a Promise in recent HA)
    let token = '';
    try {
      const hassConn = await window.hassConnection;
      if (hassConn && hassConn.auth && hassConn.auth.data) {
        token = hassConn.auth.data.access_token || '';
      }
    } catch(e) {}

    // Fetch the chat panel HTML with auth header
    let htmlContent = '';
    if (token) {
      try {
        const resp = await fetch('/api/llm_smart_assistant/chat_panel', {
          headers: { 'Authorization': 'Bearer ' + token }
        });
        if (resp.ok) {
          htmlContent = await resp.text();
        } else {
          htmlContent = '<p style="color:var(--error-color);padding:20px;">Failed to load chat panel: ' + resp.status + ' ' + resp.statusText + '</p>';
        }
      } catch(e) {
        htmlContent = '<p style="color:var(--error-color);padding:20px;">Failed to load chat panel: ' + e.message + '</p>';
      }
    } else {
      htmlContent = '<p style="color:var(--error-color);padding:20px;">No auth token available. Please log in to Home Assistant.</p>';
    }

    // Load via srcdoc so the chat_panel endpoint can require auth (the iframe
    // itself cannot send Authorization headers on initial page load).
    this.innerHTML = '<iframe srcdoc="' + htmlContent.replace(/"/g, '&quot;') + '" ' +
      'allow="microphone *" sandbox="allow-same-origin allow-scripts allow-forms allow-popups" ' +
      'style="width:100%;height:100%;border:none;display:block"></iframe>';

    // Listen for token requests from iframe and send token via postMessage
    window.addEventListener('message', (event) => {
      if (event.source === this.querySelector('iframe')?.contentWindow &&
          event.data === '__llm_auth_request__') {
        event.source.postMessage({
          type: '__llm_auth_token__',
          token: token
        }, window.location.origin);
      }
    });

    const resize = () => {
      if (!this.isConnected) { this._resizeTimer = null; return; }

      // Measure the sidebar width by finding the drawer element
      let sidebarW = 0;
      let headerH = 0;
      let el = this.parentElement;
      while (el) {
        const rect = el.getBoundingClientRect();
        if (rect.x > 0) {
          sidebarW = rect.x;
          headerH = rect.y;
          break;
        }
        el = el.parentElement;
      }

      // Position ourselves to fill the content area
      this.style.setProperty('position', 'fixed', 'important');
      this.style.setProperty('top', headerH + 'px', 'important');
      this.style.setProperty('left', sidebarW + 'px', 'important');
      this.style.setProperty('right', '0', 'important');
      this.style.setProperty('bottom', '0', 'important');
      this.style.setProperty('width', 'auto', 'important');
      this.style.setProperty('height', 'auto', 'important');
      this.style.setProperty('z-index', '10', 'important');
      this.style.setProperty('background', 'inherit', 'important');

      const iframe = this.querySelector('iframe');
      if (iframe) {
        iframe.style.setProperty('width', '100%', 'important');
        iframe.style.setProperty('height', '100%', 'important');
        iframe.style.setProperty('border', 'none', 'important');
        iframe.style.setProperty('display', 'block', 'important');
      }
    };

    // Run immediately and repeatedly until we get good dimensions
    resize();
    let tries = 0;
    this._resizeTimer = setInterval(() => {
      if (++tries > 20) { this._resizeTimer = null; return; }
      resize();
    }, 250);
  }

  disconnectedCallback() {
    if (this._resizeTimer) {
      clearInterval(this._resizeTimer);
      this._resizeTimer = null;
    }
  }
}

customElements.define("llm-chat-panel", LLMChatPanel);