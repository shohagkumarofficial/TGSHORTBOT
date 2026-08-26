/**
 * REST API Client for Telegram Game Hub
 */
const api = {
  getHeaders() {
    const headers = {
      'Content-Type': 'application/json'
    };
    const initData = window.tgApp ? window.tgApp.getInitData() : '';
    if (initData) {
      headers['X-Telegram-Init-Data'] = initData;
    }
    return headers;
  },

  async get(endpoint, params = {}) {
    const query = new URLSearchParams(params).toString();
    const url = query ? `${endpoint}?${query}` : endpoint;
    const res = await fetch(url, {
      method: 'GET',
      headers: this.getHeaders()
    });
    if (!res.ok && res.status === 401) {
      console.warn("Unauthorized API call");
    }
    return res.json();
  },

  async post(endpoint, data = {}) {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify(data)
    });
    return res.json();
  },

  // API Methods
  async getUserInfo() {
    return this.get('/api/user/info');
  },

  async startGame(gameId) {
    return this.post('/api/game/start', { game_id: gameId });
  },

  async endGame(gameId, score, result = 'completed') {
    return this.post('/api/game/end', { game_id: gameId, score, result });
  },

  async claimAdReward(network = 'adsgram') {
    return this.post('/api/ad/reward', { network });
  },

  async getLeaderboard(gameId = 'all') {
    return this.get('/api/leaderboard', { game_id: gameId });
  }
};

window.api = api;
