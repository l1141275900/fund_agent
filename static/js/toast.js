// toast.js — 自定义通知 & 确认弹窗（替代浏览器 alert/confirm）

const Toast = {
  _init() {
    if (this._ready) return;
    this.container = document.getElementById('toastContainer');
    this.confirmOverlay = document.getElementById('confirmOverlay');
    this.confirmMsg = document.getElementById('confirmMsg');
    this._ready = true;
  },

  /** info / success / error */
  show(msg, type) {
    this._init();
    type = type || 'info';
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    this.container.appendChild(el);
    setTimeout(() => {
      el.classList.add('removing');
      el.addEventListener('animationend', () => el.remove());
    }, 2500);
  },

  /** 返回 Promise<boolean>，替代 confirm() */
  confirm(msg) {
    this._init();
    return new Promise((resolve) => {
      this.confirmMsg.textContent = msg;
      this.confirmOverlay.classList.add('visible');

      const cleanup = (val) => {
        this.confirmOverlay.classList.remove('visible');
        resolve(val);
      };

      const onOk = () => cleanup(true);
      const onCancel = () => cleanup(false);
      const onClickOutside = (e) => {
        if (e.target === this.confirmOverlay) cleanup(false);
      };

      document.getElementById('confirmOkBtn').addEventListener('click', onOk, { once: true });
      document.getElementById('confirmCancelBtn').addEventListener('click', onCancel, { once: true });
      this.confirmOverlay.addEventListener('click', onClickOutside, { once: true });
    });
  }
};
