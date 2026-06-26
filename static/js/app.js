// app.js — 应用入口：session 管理、模块初始化

const App = {
  sessionKey: 'chat_session_id',

  init() {
    History.init();
    Chat.init();
    Holdings.init();
    Daily.init();

    document.getElementById('resetSessionBtn').addEventListener('click', () => History.newChat());
  },

  getSessionId() {
    let id = localStorage.getItem(this.sessionKey);
    if (!id) {
      id = this.generateUUID();
      localStorage.setItem(this.sessionKey, id);
    }
    return id;
  },

  setSessionId(id) {
    localStorage.setItem(this.sessionKey, id);
  },

  resetSession() {
    this.setSessionId(this.generateUUID());
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

  generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
  }
};

document.addEventListener('DOMContentLoaded', () => App.init());
