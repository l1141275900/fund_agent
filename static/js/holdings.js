// holdings.js — 基金持仓管理

const Holdings = {
  panel: null,
  overlay: null,
  pool: [],           // 待提交的选择池
  currentHoldings: [], // 已持有的基金

  init() {
    this.panel = document.getElementById('holdingsPanel');
    this.overlay = document.getElementById('holdingsOverlay');

    document.getElementById('toggleHoldingsBtn').addEventListener('click', () => this.open());
    document.getElementById('closeHoldingsBtn').addEventListener('click', () => this.close());
    this.overlay.addEventListener('click', () => this.close());

    document.getElementById('queryFundBtn').addEventListener('click', () => this.queryAndVerify());
    document.getElementById('fundCodeInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.queryAndVerify();
    });
    document.getElementById('submitFundsBtn').addEventListener('click', () => this.submitAll());
  },

  open() {
    this.panel.classList.add('visible');
    this.overlay.classList.add('visible');
    this.loadHoldings();
  },

  close() {
    this.panel.classList.remove('visible');
    this.overlay.classList.remove('visible');
  },

  async queryAndVerify() {
    const input = document.getElementById('fundCodeInput');
    const code = input.value.trim();
    if (!code) return;

    const resultEl = document.getElementById('fundQueryResult');
    const btn = document.getElementById('queryFundBtn');
    btn.disabled = true;
    btn.textContent = '查询中...';
    resultEl.className = 'fund-query-result visible';
    resultEl.innerHTML = '<span class="muted">正在查询...</span>';

    try {
      const data = await API.queryFund(code);
      if (!data || Object.keys(data).length === 0 || data['基金全称'] === '---') {
        resultEl.className = 'fund-query-result visible error';
        resultEl.innerHTML = `<p>未查询到基金代码 <strong>${this.esc(code)}</strong> 对应的基金，请检查代码是否正确。</p>`;
        btn.disabled = false;
        btn.textContent = '查询验证';
        return;
      }
      this._lastQueryResult = data;
      resultEl.className = 'fund-query-result visible success';
      resultEl.innerHTML = `
        <div class="fund-detail"><strong>基金代码：</strong>${this.esc(data['基金代码'])}</div>
        <div class="fund-detail"><strong>基金简称：</strong>${this.esc(data['基金简称'])}</div>
        <div class="fund-detail"><strong>基金类型：</strong>${this.esc(data['基金类型'])}</div>
        <div class="fund-detail"><strong>基金经理：</strong>${this.esc(data['基金经理人'])}</div>
        <div class="fund-detail"><strong>管理人：</strong>${this.esc(data['基金管理人'])}</div>
        <div class="fund-detail"><strong>净资产规模：</strong>${this.esc(String(data['净资产规模']))}</div>
        <div class="fund-detail"><strong>管理费率：</strong>${this.esc(String(data['管理费率']))}</div>
        <div class="fund-query-actions">
          <button class="btn btn-primary btn-sm" id="confirmAddBtn">✓ 确认添加</button>
          <button class="btn btn-outline btn-sm" id="cancelAddBtn">重新输入</button>
        </div>
      `;
      document.getElementById('confirmAddBtn').addEventListener('click', () => this.addToPool());
      document.getElementById('cancelAddBtn').addEventListener('click', () => {
        resultEl.className = 'fund-query-result';
        resultEl.innerHTML = '';
        input.value = '';
        input.focus();
      });
    } catch (err) {
      resultEl.className = 'fund-query-result visible error';
      resultEl.innerHTML = `<p>查询失败：${this.esc(err.message)}</p>`;
    }
    btn.disabled = false;
    btn.textContent = '查询验证';
  },

  addToPool() {
    const data = this._lastQueryResult;
    if (!data) return;

    // 去重
    if (this.pool.some(f => f['基金代码'] === data['基金代码'])) {
      Toast.show('该基金已在选择池中', 'info');
      return;
    }
    if (this.currentHoldings.some(f => f.code === data['基金代码'])) {
      Toast.show('该基金已在持仓列表中', 'info');
      return;
    }

    this.pool.push(data);
    this.renderPool();
    document.getElementById('fundCodeInput').value = '';
    document.getElementById('fundQueryResult').className = 'fund-query-result';
    document.getElementById('fundQueryResult').innerHTML = '';
    this._lastQueryResult = null;
  },

  removeFromPool(index) {
    this.pool.splice(index, 1);
    this.renderPool();
  },

  renderPool() {
    const container = document.getElementById('selectionPool');
    const submitBtn = document.getElementById('submitFundsBtn');

    if (this.pool.length === 0) {
      container.innerHTML = '';
      submitBtn.style.display = 'none';
      return;
    }
    submitBtn.style.display = 'inline-flex';
    container.innerHTML = this.pool.map((f, i) => `
      <div class="selection-item">
        <span><strong>${this.esc(f['基金代码'])}</strong> ${this.esc(f['基金简称'])}</span>
        <button class="remove-btn" data-index="${i}" title="移除">&times;</button>
      </div>
    `).join('');

    container.querySelectorAll('.remove-btn').forEach(btn => {
      btn.addEventListener('click', (e) => this.removeFromPool(parseInt(e.target.dataset.index)));
    });
  },

  async submitAll() {
    if (this.pool.length === 0) return;
    const btn = document.getElementById('submitFundsBtn');
    btn.disabled = true;
    btn.textContent = '提交中...';

    try {
      const result = await API.submitFunds(this.pool);
      this.pool = [];
      this.renderPool();
      this.loadHoldings();
      Toast.show('提交成功', 'success');
    } catch (err) {
      Toast.show('提交失败：' + err.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = '提交全部';
  },

  async loadHoldings() {
    const container = document.getElementById('holdingsList');
    try {
      const data = await API.getHoldings();
      this.currentHoldings = data;
      if (!data || data.length === 0) {
        container.innerHTML = '<p class="muted">暂无持仓基金</p>';
        return;
      }
      container.innerHTML = data.map(f => `
        <div class="holding-card">
          <div class="hc-name">${this.esc(f.name)}</div>
          <div class="hc-info">
            代码：${this.esc(f.code)} &nbsp;|&nbsp;
            类型：${this.esc(f.fund_type || '-')} &nbsp;|&nbsp;
            规模：${this.esc(String(f.scale || '-'))}
          </div>
          <div class="hc-info">
            经理：${this.esc(f.manager || '-')} &nbsp;|&nbsp;
            公司：${this.esc(f.company || '-')}
          </div>
          <div class="hc-actions">
            <button class="btn btn-outline btn-sm delete-holding" data-code="${this.esc(f.code)}">删除</button>
          </div>
        </div>
      `).join('');

      container.querySelectorAll('.delete-holding').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          const code = e.target.dataset.code;
          if (!(await Toast.confirm(`确定要删除基金 ${code} 吗？`))) return;
          await API.removeFund(code);
          this.loadHoldings();
        });
      });
    } catch (err) {
      container.innerHTML = `<p class="muted">加载失败：${this.esc(err.message)}</p>`;
    }
  },

  esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
};
