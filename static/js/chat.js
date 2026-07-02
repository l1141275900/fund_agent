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
  // 多 Agent 可观察性状态
  currentAgentName: null,
  currentAgentGroup: null,
  agentCollapsed: {},        // 记录哪些 agent-group 被手动折叠

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

  /* ===== 多 Agent 分组 ===== */

  // Agent 名 → 友好图标 + CSS class
  formatAgentLabel(name) {
    const map = {
      'main_agent':     { icon: '🧠', label: '主调度', cls: 'agent-main' },
      'SearchAgent':    { icon: '🔍', label: '搜索', cls: 'agent-search' },
      'Buffett_Warren': { icon: '📊', label: '巴菲特', cls: 'agent-master' },
      'Bogle_John':     { icon: '📈', label: '博格尔', cls: 'agent-master' },
      'Duan_Yongping':  { icon: '💡', label: '段永平', cls: 'agent-master' },
    };
    return map[name] || { icon: '🤖', label: name, cls: 'agent-default' };
  },

  // 创建 Agent 分组 DOM，挂到当前消息气泡下
  createAgentGroup(agentName) {
    const info = this.formatAgentLabel(agentName);
    const group = document.createElement('div');
    group.className = `agent-group ${info.cls}`;
    group.dataset.agent = agentName;

    const header = document.createElement('div');
    header.className = 'agent-header';
    header.innerHTML = `
      <span class="agent-dot running"></span>
      <span class="agent-label">${info.icon} ${info.label}</span>
      <span class="agent-status">运行中...</span>
    `;
    // 点击头部折叠/展开
    header.addEventListener('click', () => {
      group.classList.toggle('collapsed');
      this.agentCollapsed[agentName] = group.classList.contains('collapsed');
    });

    const body = document.createElement('div');
    body.className = 'agent-body';

    group.appendChild(header);
    group.appendChild(body);

    const bubble = this.currentMsg.querySelector('.msg-bubble');
    const cursor = bubble.querySelector('.cursor');
    if (cursor) {
      bubble.insertBefore(group, cursor);
    } else {
      bubble.appendChild(group);
    }
    return group;
  },

  // 确保当前活跃 Agent 有对应分组。Agent 切换时自动完成旧分组、创建新分组
  ensureAgentGroup(agentName) {
    if (agentName !== this.currentAgentName) {
      // 完成上一个 agent 分组
      if (this.currentAgentGroup) {
        const dot = this.currentAgentGroup.querySelector('.agent-dot');
        const status = this.currentAgentGroup.querySelector('.agent-status');
        if (dot) { dot.classList.remove('running'); dot.classList.add('done'); }
        if (status) status.textContent = '完成';
        this.currentAgentGroup.classList.add('agent-done');
        // 恢复折叠偏好
        if (this.agentCollapsed[this.currentAgentName]) {
          this.currentAgentGroup.classList.add('collapsed');
        }
      }
      // 创建新分组
      this.currentAgentGroup = this.createAgentGroup(agentName);
      this.currentAgentName = agentName;
    }
    return this.currentAgentGroup;
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
    this.currentAgentName = null;
    this.currentAgentGroup = null;

    let fullContent = '';
    let historyLoaded = false;

    // 获取当前 Agent 分组的 body 容器（用于插入 block）
    const agentBody = () => {
      const group = this.currentAgentGroup || this.ensureAgentGroup('main_agent');
      return group.querySelector('.agent-body');
    };

    const callbacks = {
      onContent: (text, agentName) => {
        if (!historyLoaded) { History.loadList(); historyLoaded = true; }
        const body = this.ensureAgentGroup(agentName).querySelector('.agent-body');
        if (this.lastBlockType === 'content' && this.lastBlockEl && this.lastBlockEl.closest('.agent-group') === this.currentAgentGroup) {
          fullContent += text;
          this.lastBlockEl.innerHTML = marked.parse(fullContent);
        } else {
          fullContent = text;
          this.lastBlockEl = this.addBlockToBody(body, 'text');
          this.lastBlockEl.innerHTML = marked.parse(text);
          this.lastBlockType = 'content';
        }
        this.scrollBottom();
      },

      onReasoning: (text, agentName) => {
        if (!historyLoaded) { History.loadList(); historyLoaded = true; }
        const body = this.ensureAgentGroup(agentName).querySelector('.agent-body');
        if (this.lastBlockType === 'reasoning' && this.lastBlockEl && this.lastBlockEl.closest('.agent-group') === this.currentAgentGroup) {
          const reText = this.lastBlockEl.querySelector('.re-text');
          reText.textContent += text;
        } else {
          this.lastBlockEl = this.addBlockToBody(body, 'reasoning');
          this.lastBlockType = 'reasoning';
          const reText = this.lastBlockEl.querySelector('.re-text');
          reText.textContent = text;
        }
        this.scrollBottom();
      },

      onToolCalling: (nameWithArgs, agentName, isDelegate) => {
        if (!historyLoaded) { History.loadList(); historyLoaded = true; }
        if (isDelegate) {
          // delegate_* 工具：子 Agent 启动信号，创建新的 agent-group
          // 从 tool 名提取子 Agent 信息：delegate_search_subagent → SearchAgent
          // 但 agent_name 仍然指向 main_agent（因为 tool_calling 是主 agent 发出的）
          // 实际子 Agent 的内容帧会带自己的 agent_name
        } else {
          const body = this.ensureAgentGroup(agentName).querySelector('.agent-body');
          const block = this.addBlockToBody(body, 'tool');
          const dot = block.querySelector('.tl-dot');
          dot.className = 'tl-dot running';
          block.querySelector('.tl-name').textContent = nameWithArgs;
          this.currentToolCalls.push({ el: block, name: nameWithArgs });
          this.lastBlockType = 'tool';
          this.lastBlockEl = block;
          this.toolTimers[nameWithArgs] = setTimeout(() => {
            const hint = document.createElement('div');
            hint.className = 'tl-hint';
            hint.textContent = '大数据集加载中，请耐心等待...';
            block.appendChild(hint);
          }, 5000);
        }
        this.scrollBottom();
      },

      onToolResult: (nameWithArgs, result, agentName) => {
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
        const body = this.currentAgentGroup
          ? this.currentAgentGroup.querySelector('.agent-body')
          : this.currentMsg.querySelector('.msg-bubble');
        const errBlock = this.addBlockToBody(body, 'text');
        errBlock.innerHTML = `<span style="color:var(--red)">[错误] ${this.esc(err)}</span>`;
        this.finalize();
      }
    };

    const sessionId = App.getSessionId();
    API.streamChat(sessionId, query, callbacks);
  },

  finalize() {
    // 完成当前 agent 分组
    if (this.currentAgentGroup) {
      const dot = this.currentAgentGroup.querySelector('.agent-dot');
      const status = this.currentAgentGroup.querySelector('.agent-status');
      if (dot) { dot.classList.remove('running'); dot.classList.add('done'); }
      if (status) status.textContent = '完成';
      this.currentAgentGroup.classList.add('agent-done');
    }
    // 移除光标
    if (this.currentMsg) {
      const cursor = this.currentMsg.querySelector('.cursor');
      if (cursor) cursor.remove();
    }
    this.currentMsg = null;
    this.currentAgentName = null;
    this.currentAgentGroup = null;
    this.currentToolCalls = [];
    Object.values(this.toolTimers).forEach(clearTimeout);
    this.toolTimers = {};
    this.lastBlockType = null;
    this.lastBlockEl = null;
    this.sending = false;
    this.sendBtn.disabled = false;
    this.input.focus();
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

  // 在指定容器内插入 block（通用），在 cursor 之前
  addBlockToBody(body, type) {
    const block = document.createElement('div');
    block.className = `block block-${type}`;

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

    body.appendChild(block);
    return block;
  },

  addBlock(msgGroup, type) {
    const bubble = msgGroup.querySelector('.msg-bubble');
    return this.addBlockToBody(bubble, type);
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
