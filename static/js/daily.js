// daily.js — 每日关注板块

const Daily = {
  storageKey: 'daily_focus',
  presetPrompt: '请分析今日值得关注的基金板块和投资方向，给出简洁的结论和建议（不超过500字）。',
  loading: false,

  init() {
    document.getElementById('dailyRefreshBtn').addEventListener('click', () => this.refresh());

    const cached = this.getCache();
    if (cached) {
      this.render(cached.content, cached.date);
    }

    this.checkAndTrigger();
    setInterval(() => this.checkAndTrigger(), 60000);
  },

  getCache() {
    try {
      const raw = localStorage.getItem(this.storageKey);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch { return null; }
  },

  setCache(content) {
    const today = new Date().toISOString().slice(0, 10);
    localStorage.setItem(this.storageKey, JSON.stringify({ date: today, content }));
  },

  checkAndTrigger() {
    const now = new Date();
    const cached = this.getCache();
    const today = now.toISOString().slice(0, 10);
    if (cached && cached.date === today) return;
    if (now.getHours() < 9) return;
    this.refresh();
  },

  async refresh() {
    if (this.loading) return;
    this.loading = true;

    const body = document.getElementById('dailyBody');
    body.innerHTML = '<div class="daily-loading"><span class="pulse"></span>正在生成每日关注报告...</div>';

    let fullContent = '';

    try {
      await API.streamChat('daily_focus', this.presetPrompt, {
        onContent: (text) => { fullContent += text; },
        onDone: () => {
          this.loading = false;
          const idx = fullContent.indexOf('[finish]');
          const content = idx >= 0 ? fullContent.slice(idx + 8).trim() : fullContent.trim();
          if (content) {
            this.setCache(content);
            this.render(content);
          } else {
            body.innerHTML = '<p class="muted" style="padding-top:20px;text-align:center">生成失败，请手动刷新</p>';
          }
        },
        onError: (err) => {
          this.loading = false;
          body.innerHTML = `<p class="muted" style="padding-top:20px;text-align:center">生成失败：${err}</p>`;
        }
      });
    } catch (err) {
      this.loading = false;
      body.innerHTML = `<p class="muted" style="padding-top:20px;text-align:center">请求失败：${err.message}</p>`;
    }
  },

  render(content, date) {
    const body = document.getElementById('dailyBody');
    const displayDate = date || new Date().toISOString().slice(0, 10);
    body.innerHTML = `
      <div class="daily-body">
        <p style="color:var(--text-muted);font-size:12px;">${displayDate}</p>
        <div>${marked.parse(content)}</div>
      </div>
    `;
  }
};
