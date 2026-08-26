/**
 * Game Hub Application Controller
 */
const hub = {
  user: null,
  games: [],
  settings: {},
  regenTimerInterval: null,
  secondsUntilRegen: 0,

  async init() {
    this.setupEventListeners();
    await this.loadData();
  },

  setupEventListeners() {
    // Tab items
    document.querySelectorAll('.tab-item').forEach(tab => {
      tab.addEventListener('click', () => {
        window.tgApp?.hapticSelection();
        this.switchTab(tab.dataset.tab);
      });
    });

    // Refill ad button in banner
    const btnRefill = document.getElementById('btn-refill-ad');
    if (btnRefill) {
      btnRefill.addEventListener('click', () => this.handleWatchAd());
    }

    // Modal watch ad button
    const btnModalAd = document.getElementById('btn-modal-watch-ad');
    if (btnModalAd) {
      btnModalAd.addEventListener('click', () => {
        this.closeModal();
        this.handleWatchAd();
      });
    }

    // Modal close button
    const btnModalClose = document.getElementById('btn-modal-close');
    if (btnModalClose) {
      btnModalClose.addEventListener('click', () => this.closeModal());
    }

    // Lives badge click
    const livesBadge = document.querySelector('.lives-badge');
    if (livesBadge) {
      livesBadge.addEventListener('click', () => {
        if (this.user && this.user.lives < this.user.max_lives) {
          this.handleWatchAd();
        } else {
          this.showToast("Your lives are currently FULL! ❤️");
        }
      });
    }
  },

  async loadData() {
    try {
      const data = await window.api.getUserInfo();
      if (data && data.success) {
        this.user = data.user;
        this.games = data.games || [];
        this.settings = data.settings || {};
        this.secondsUntilRegen = this.user.seconds_until_regen || 0;

        // Init ads
        window.adManager.init(this.settings);

        this.renderUser();
        this.renderGames();
        this.startRegenTimer();
      }
    } catch (e) {
      console.error("Failed to load hub data:", e);
      this.showToast("Failed to connect to game server.");
    }
  },

  renderUser() {
    if (!this.user) return;

    // Avatar Initial
    const avatarEl = document.getElementById('user-avatar');
    if (avatarEl) {
      const initial = (this.user.first_name || this.user.username || 'P')[0].toUpperCase();
      avatarEl.textContent = initial;
    }

    // Username
    const usernameEl = document.getElementById('user-name');
    if (usernameEl) {
      usernameEl.textContent = this.user.first_name || this.user.username || 'Player';
    }

    // Lives
    const livesCountEl = document.getElementById('lives-count');
    if (livesCountEl) {
      livesCountEl.textContent = `${this.user.lives}/${this.user.max_lives}`;
    }

    this.updateRegenTimerUI();
  },

  startRegenTimer() {
    if (this.regenTimerInterval) clearInterval(this.regenTimerInterval);

    this.regenTimerInterval = setInterval(() => {
      if (this.user && this.user.lives < this.user.max_lives) {
        if (this.secondsUntilRegen > 0) {
          this.secondsUntilRegen--;
          this.updateRegenTimerUI();
        } else {
          // Time expired, refresh user data
          this.loadData();
        }
      } else {
        this.updateRegenTimerUI();
      }
    }, 1000);
  },

  updateRegenTimerUI() {
    const timerEl = document.getElementById('regen-timer');
    if (!timerEl) return;

    if (!this.user || this.user.lives >= this.user.max_lives) {
      timerEl.textContent = 'Full ❤️';
      timerEl.style.color = 'var(--accent-green)';
    } else {
      const minutes = Math.floor(this.secondsUntilRegen / 60);
      const seconds = this.secondsUntilRegen % 60;
      const fmt = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
      timerEl.textContent = `+1 ❤️ in ${fmt}`;
      timerEl.style.color = 'var(--text-muted)';
    }
  },

  renderGames() {
    const container = document.getElementById('games-grid');
    if (!container) return;
    container.innerHTML = '';

    const iconClasses = {
      snake: 'icon-snake',
      '2048': 'icon-2048',
      flappy: 'icon-flappy',
      tictactoe: 'icon-tictactoe',
      memory: 'icon-memory',
      whack: 'icon-whack'
    };

    const emojis = {
      snake: '🐍',
      '2048': '🔢',
      flappy: '🕊️',
      tictactoe: '❌',
      memory: '🧠',
      whack: '🔨'
    };

    this.games.forEach(g => {
      const card = document.createElement('div');
      card.className = `game-card ${g.enabled ? '' : 'disabled'}`;
      card.innerHTML = `
        <div class="game-card-icon ${iconClasses[g.id] || ''}">
          ${emojis[g.id] || '🎮'}
        </div>
        <div class="game-card-title">${g.name.replace(/^[^\s]+\s/, '')}</div>
        <div class="game-card-score">Best: <span>${g.high_score || 0}</span></div>
        <button class="btn-play-game" data-id="${g.id}">
          ${g.enabled ? '▶ PLAY' : 'LOCKED'}
        </button>
      `;

      if (g.enabled) {
        card.addEventListener('click', () => this.launchGame(g.id));
      }
      container.appendChild(card);
    });
  },

  async launchGame(gameId) {
    window.tgApp?.hapticImpact('light');

    if (!this.user || this.user.lives <= 0) {
      this.showNoLivesModal();
      return;
    }

    // Call start game API
    const startRes = await window.api.startGame(gameId);
    if (!startRes.success) {
      if (startRes.error === 'no_lives') {
        this.showNoLivesModal();
      } else {
        this.showToast(startRes.message || "Failed to start game.");
      }
      return;
    }

    // Update local lives if deducted on start
    if (startRes.lives !== undefined) {
      this.user.lives = startRes.lives;
      this.renderUser();
    }

    // Navigate to game view
    window.location.href = `/static/games/${gameId}/index.html`;
  },

  handleWatchAd() {
    window.tgApp?.hapticImpact('medium');
    window.adManager.showRewardedAd(
      (rewardRes) => {
        // Success
        if (rewardRes.lives !== undefined) {
          this.user.lives = rewardRes.lives;
          this.secondsUntilRegen = rewardRes.seconds_until_regen || 0;
          this.renderUser();
        }
      },
      (errorMsg) => {
        // Error / skipped
        if (errorMsg) this.showToast(errorMsg);
      }
    );
  },

  showNoLivesModal() {
    window.tgApp?.hapticNotification('warning');
    const modal = document.getElementById('no-lives-modal');
    if (modal) modal.classList.add('active');
  },

  closeModal() {
    const modal = document.getElementById('no-lives-modal');
    if (modal) modal.classList.remove('active');
  },

  switchTab(tabName) {
    document.querySelectorAll('.tab-item').forEach(t => {
      t.classList.toggle('active', t.dataset.tab === tabName);
    });
    document.querySelectorAll('.tab-content').forEach(c => {
      c.classList.toggle('active', c.id === `tab-${tabName}`);
    });

    if (tabName === 'leaderboard') {
      this.loadLeaderboard();
    }
  },

  async loadLeaderboard() {
    const listEl = document.getElementById('leaderboard-list');
    if (!listEl) return;
    listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">Loading rankings...</div>';

    try {
      const data = await window.api.getLeaderboard('all');
      if (data && data.leaderboard && data.leaderboard.length > 0) {
        listEl.innerHTML = '';
        data.leaderboard.forEach(item => {
          let rankClass = '';
          let rankIcon = item.rank;
          if (item.rank === 1) { rankClass = 'gold'; rankIcon = '🥇'; }
          else if (item.rank === 2) { rankClass = 'silver'; rankIcon = '🥈'; }
          else if (item.rank === 3) { rankClass = 'bronze'; rankIcon = '🥉'; }

          const row = document.createElement('div');
          row.className = 'leaderboard-item';
          row.innerHTML = `
            <div class="lb-left">
              <div class="lb-rank ${rankClass}">${rankIcon}</div>
              <div class="lb-name">${item.name}</div>
            </div>
            <div class="lb-score">${item.score} pts</div>
          `;
          listEl.appendChild(row);
        });
      } else {
        listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">No leaderboard entries yet. Play a game to rank #1!</div>';
      }
    } catch (e) {
      listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">Failed to load leaderboard.</div>';
    }
  },

  showToast(msg) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => {
      toast.classList.remove('show');
    }, 3200);
  }
};

window.hub = hub;
document.addEventListener('DOMContentLoaded', () => hub.init());
