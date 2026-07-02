// api.js — 后端 API 请求封装

const API = {
  async streamChat(sessionId, query, callbacks) {
    try {
      const resp = await fetch('/chat/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, query: query })
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data:')) {
            const jsonStr = line.slice(5).trim();
            if (!jsonStr) continue;
            try {
              const data = JSON.parse(jsonStr);
              if (data.content != null && data.content !== '') {
                callbacks.onContent && callbacks.onContent(data.content, data.agent_name || 'main_agent');
                // 让出事件循环，浏览器得以在 token 之间重绘，实现流式输出
                await new Promise(r => setTimeout(r, 0));
              }
              if (data.reasoning_content != null && data.reasoning_content !== '') {
                callbacks.onReasoning && callbacks.onReasoning(data.reasoning_content, data.agent_name || 'main_agent');
              }
              if (data.tool_call_result != null) {
                callbacks.onToolResult && callbacks.onToolResult(data.tool_calling, data.tool_call_result, data.agent_name || 'main_agent');
              } else if (data.tool_calling != null && data.tool_calling !== '') {
                const isDelegate = typeof data.tool_calling === 'string' && data.tool_calling.startsWith('delegate_');
                callbacks.onToolCalling && callbacks.onToolCalling(data.tool_calling, data.agent_name || 'main_agent', isDelegate);
              }
            } catch (e) { /* skip malformed JSON */ }
          }
        }
      }
      callbacks.onDone && callbacks.onDone();
    } catch (err) {
      callbacks.onError && callbacks.onError(err.message);
    }
  },

  async getSessions() {
    const resp = await fetch('/chat/sessions');
    return resp.json();
  },

  async getMessages(sessionId) {
    const resp = await fetch(`/chat/messages?session_id=${encodeURIComponent(sessionId)}`);
    return resp.json();
  },

  async deleteSession(sessionId) {
    const resp = await fetch(`/chat/session?session_id=${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
    return resp.json();
  },

  async queryFund(fundCode) {
    const resp = await fetch(`/fund/query_fund?fund_code=${encodeURIComponent(fundCode)}`);
    return resp.json();
  },

  async getHoldings() {
    const resp = await fetch('/fund/holdings');
    return resp.json();
  },

  async submitFunds(fundList) {
    const resp = await fetch('/fund/submit_fund', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fund_code_list: fundList })
    });
    return resp.json();
  },

  async removeFund(fundCode) {
    const resp = await fetch(`/fund/remove_fund?fund_code=${encodeURIComponent(fundCode)}`, {
      method: 'DELETE'
    });
    return resp.json();
  },

  async getFundNav(fundCode) {
    const resp = await fetch(`/fund/get_fund_nav?fund_code=${encodeURIComponent(fundCode)}`);
    return resp.json();
  }
};
