// chat.js — 对话助手 UI（时间顺序混合块 + Markdown）

const Chat = {
  container: null,
  input: null,
  sendBtn: null,
  currentMsg: null,
  currentToolCalls: [],
  toolTimers: {},
  lastBlockType: null,
  lastBlockEl: null,
  sending: false,

  init() {
    this.container = document.getElementById('chatMessages');
    this.input = document.getElementById('chatInput');
    this.sendBtn = document.getElementById('sendBtn');

    this.sendBtn.addEventListener('click', () => this.send());
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
    });
  },

  async send() {
    const query = this.input.value.trim();
    if (!query || this.sending) return;

    this.sending = true;
    this.sendBtn.disabled = true;
    this.input.value = '';
    this.input.style.height = 'auto';

    const welcome = this.container.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    // 用户消息
    this.addUserMessage(query);
    this.scrollBottom();

    // 助手消息容器
    this.currentMsg = this.createMsgGroup('assistant');
    this.currentToolCalls = [];
    this.lastBlockType = null;
    this.lastBlockEl = null;

    let fullContent = '';
    let historyLoaded = false;

    const callbacks = {
      onContent: (text) => {
        if (!historyLoaded) { History.loadList(); historyLoaded = true; }
        if (this.lastBlockType === 'content' && this.lastBlockEl) {
          fullContent += text;
          this.lastBlockEl.innerHTML = marked.parse(fullContent);
        } else {
          fullContent = text;
          this.lastBlockEl = this.addBlock(this.currentMsg, 'text');
          this.lastBlockEl.innerHTML = marked.parse(text);
          this.lastBlockType = 'content';
        }
        this.scrollBottom();
      },

      onReasoning: (text) => {
        if (!historyLoaded) { History.loadList(); historyLoaded = true; }
        if (this.lastBlockType === 'reasoning' && this.lastBlockEl) {
          const reText = this.lastBlockEl.querySelector('.re-text');
          reText.textContent += text;
        } else {
          this.lastBlockEl = this.addBlock(this.currentMsg, 'reasoning');
          this.lastBlockType = 'reasoning';
          const reText = this.lastBlockEl.querySelector('.re-text');
          reText.textContent = text;
        }
        this.scrollBottom();
      },

      onToolCalling: (nameWithArgs) => {
        if (!historyLoaded) { History.loadList(); historyLoaded = true; }
        const block = this.addBlock(this.currentMsg, 'tool');
        const dot = block.querySelector('.tl-dot');
        dot.className = 'tl-dot running';
        block.querySelector('.tl-name').textContent = nameWithArgs;
        this.currentToolCalls.push({ el: block, name: nameWithArgs });
        this.lastBlockType = 'tool';
        this.lastBlockEl = block;
        // 5 秒后若仍未返回，显示弱提示
        this.toolTimers[nameWithArgs] = setTimeout(() => {
          const hint = document.createElement('div');
          hint.className = 'tl-hint';
          hint.textContent = '大数据集加载中，请耐心等待...';
          block.appendChild(hint);
        }, 5000);
        this.scrollBottom();
      },

      onToolResult: (nameWithArgs, result) => {
        const match = this.currentToolCalls.find(t => t.name === nameWithArgs);
        if (match) {
          clearTimeout(this.toolTimers[nameWithArgs]);
          delete this.toolTimers[nameWithArgs];
          const hint = match.el.querySelector('.tl-hint');
          if (hint) hint.remove();
          const dot = match.el.querySelector('.tl-dot');
          dot.className = 'tl-dot done';
          match.el.querySelector('.tl-result').textContent = result;
          match.el.classList.add('expanded');
        }
        this.scrollBottom();
      },

      onDone: () => {
        this.finalize();
      },

      onError: (err) => {
        const errBlock = this.addBlock(this.currentMsg, 'text');
        errBlock.innerHTML = `<span style="color:var(--red)">[错误] ${this.esc(err)}</span>`;
        this.finalize();
      }
    };

    const sessionId = App.getSessionId();
    API.streamChat(sessionId, query, callbacks);
  },

  finalize() {
    // 移除光标
    if (this.currentMsg) {
      const cursor = this.currentMsg.querySelector('.cursor');
      if (cursor) cursor.remove();
    }
    this.currentMsg = null;
    this.currentToolCalls = [];
    Object.values(this.toolTimers).forEach(clearTimeout);
    this.toolTimers = {};
    this.lastBlockType = null;
    this.lastBlockEl = null;
    this.sending = false;
    this.sendBtn.disabled = false;
    this.input.focus();
    // 刷新历史列表
    History.loadList();
  },

  /* ===== DOM Helpers ===== */

  addUserMessage(text) {
    const group = document.createElement('div');
    group.className = 'msg-group user';
    group.innerHTML = `<div class="msg-bubble">${this.esc(text)}</div>`;
    this.container.appendChild(group);
  },

  createMsgGroup(role) {
    const group = document.createElement('div');
    group.className = `msg-group ${role}`;
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    const cursor = document.createElement('span');
    cursor.className = 'cursor';
    bubble.appendChild(cursor);
    group.appendChild(bubble);
    this.container.appendChild(group);
    return group;
  },

  addBlock(msgGroup, type) {
    const block = document.createElement('div');
    block.className = `block block-${type}`;
    const bubble = msgGroup.querySelector('.msg-bubble');

    if (type === 'reasoning') {
      block.classList.add('expanded');
      const label = document.createElement('span');
      label.className = 're-label';
      label.textContent = '思考 ▾';
      const text = document.createElement('span');
      text.className = 're-text';
      block.appendChild(label);
      block.appendChild(text);
      block.addEventListener('click', () => {
        block.classList.toggle('expanded');
        label.textContent = block.classList.contains('expanded') ? '思考 ▾' : '思考 ▸';
      });
    } else if (type === 'tool') {
      const header = document.createElement('div');
      header.className = 'tl-header';
      const dot = document.createElement('span');
      dot.className = 'tl-dot';
      const name = document.createElement('span');
      name.className = 'tl-name';
      const result = document.createElement('div');
      result.className = 'tl-result';
      header.appendChild(dot);
      header.appendChild(name);
      block.appendChild(header);
      block.appendChild(result);
      block.addEventListener('click', () => block.classList.toggle('expanded'));
    }

    // 在 cursor 之前插入
    const cursor = bubble.querySelector('.cursor');
    if (cursor) {
      bubble.insertBefore(block, cursor);
    } else {
      bubble.appendChild(block);
    }
    return block;
  },

  /* ===== 渲染历史消息（静态展示，无流式） ===== */
  renderHistoryMessages(messages) {
    this.container.innerHTML = '';
    for (const msg of messages) {
      const group = document.createElement('div');
      group.className = 'msg-group msg-history';
      if (msg.role === 'user') {
        group.classList.add('user');
        group.innerHTML = `<div class="msg-bubble">${this.esc(msg.content)}</div>`;
      } else {
        group.classList.add('assistant');
        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble';
        const block = document.createElement('div');
        block.className = 'block block-text';
        block.innerHTML = marked.parse(msg.content);
        bubble.appendChild(block);
        group.appendChild(bubble);
      }
      this.container.appendChild(group);
    }
    this.scrollBottom();
  },

  scrollBottom() {
    this.container.scrollTop = this.container.scrollHeight;
  },

  esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
};
