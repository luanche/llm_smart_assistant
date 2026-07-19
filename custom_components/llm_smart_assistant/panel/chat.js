/**
 * AI Chat Panel - LLM Smart Assistant
 * Uses fixed positioning to fill the content area next to the sidebar.
 */
class LLMChatPanel extends HTMLElement {
  connectedCallback() {
    this.innerHTML = '<iframe src="/api/llm_smart_assistant/chat_panel" ' +
      'allow="microphone *" sandbox="allow-same-origin allow-scripts allow-forms allow-popups"></iframe>';

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
