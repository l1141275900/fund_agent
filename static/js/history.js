// history.js — 对话历史侧边栏

const History = {
  container: null,
  activeId: null,

  async init() {
    this.container = document.getElementById('historyList');
    this.activeId = App.getSessionId();
    await this.loadList();
    // 页面加载时自动展示当前 session 的历史消息
    try {
      const messages = await API.getMessages(this.activeId);
      if (messages && messages.length > 0) {
        Chat.renderHistoryMessages(messages);
      }
    } catch (err) { /* 无历史消息，保持欢迎页 */ }
  },

  async loadList() {
    try {
      const sessions = await API.getSessions();
      if (!sessions || sessions.length === 0) {
        this.container.innerHTML = '<p class="muted" style="padding:12px">暂无对话记录</p>';
        return;
      }
      this.container.innerHTML = sessions.map(s => `
        <div class="history-item${s.session_id === this.activeId ? ' active' : ''}" data-sid="${this.esc(s.session_id)}">
          <span class="hi-title" title="${this.esc(s.title)}">${this.esc(s.title)}</span>
          <span class="hi-time">${this.fmtTime(s.updated_at)}</span>
          <span class="hi-delete" data-sid="${this.esc(s.session_id)}">×</span>
        </div>
      `).join('');

      // 点击切换 session
      this.container.querySelectorAll('.history-item').forEach(item => {
        item.addEventListener('click', (e) => {
          if (e.target.classList.contains('hi-delete')) return;
          const sid = item.dataset.sid;
          if (sid !== this.activeId) this.switchTo(sid);
        });
      });

      // 删除 session
      this.container.querySelectorAll('.hi-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const sid = btn.dataset.sid;
          if (!(await Toast.confirm('确定要删除该对话吗？'))) return;
          await API.deleteSession(sid);
          if (sid === this.activeId) {
            App.resetSession();
          }
          this.loadList();
        });
      });
    } catch (err) {
      this.container.innerHTML = `<p class="muted" style="padding:12px">加载失败</p>`;
    }
  },

  async switchTo(sessionId) {
    this.activeId = sessionId;
    App.setSessionId(sessionId);
    this.loadList();

    try {
      const messages = await API.getMessages(sessionId);
      if (messages && messages.length > 0) {
        Chat.renderHistoryMessages(messages);
      } else {
        const container = document.getElementById('chatMessages');
        container.innerHTML = `
          <div class="chat-welcome">
            <p>你好，我是基金分析助手。可以帮你：</p>
            <ul>
              <li>查询和分析基金数据</li>
              <li>获取基金排名和净值信息</li>
              <li>解答基金投资相关问题</li>
            </ul>
          </div>`;
      }
    } catch (err) {
      console.error('加载消息失败', err);
    }
  },

  newChat() {
    const newId = App.generateUUID();
    App.setSessionId(newId);
    this.activeId = newId;
    this.loadList();
    const container = document.getElementById('chatMessages');
    container.innerHTML = `
      <div class="chat-welcome">
        <p>你好，我是基金分析助手。可以帮你：</p>
        <ul>
          <li>查询和分析基金数据</li>
          <li>获取基金排名和净值信息</li>
          <li>解答基金投资相关问题</li>
        </ul>
      </div>`;
  },

  fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diff = now - d;
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
    if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
    return `${d.getMonth()+1}/${d.getDate()}`;
  },

  esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
};
