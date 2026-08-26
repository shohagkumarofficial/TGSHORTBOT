/**
 * Game Hub Application Controller (9 Games with SVGs & Sound Engine)
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
    // Tab switching
    document.querySelectorAll('.tab-item').forEach(tab => {
      tab.addEventListener('click', () => {
        window.soundManager?.playClick();
        window.tgApp?.hapticSelection();
        this.switchTab(tab.dataset.tab);
      });
    });

    // Sound toggle button
    const soundBtn = document.getElementById('btn-sound-toggle');
    if (soundBtn) {
      soundBtn.addEventListener('click', () => {
        const isMuted = window.soundManager?.toggleMute();
        this.showToast(isMuted ? "Sound Muted 🔇" : "Sound Enabled 🔊");
      });
    }

    // Refill ad button
    const btnRefill = document.getElementById('btn-refill-ad');
    if (btnRefill) {
      btnRefill.addEventListener('click', () => {
        window.soundManager?.playClick();
        this.handleWatchAd();
      });
    }

    // Modal watch ad button
    const btnModalAd = document.getElementById('btn-modal-watch-ad');
    if (btnModalAd) {
      btnModalAd.addEventListener('click', () => {
        window.soundManager?.playClick();
        this.closeModal();
        this.handleWatchAd();
      });
    }

    // Modal close button
    const btnModalClose = document.getElementById('btn-modal-close');
    if (btnModalClose) {
      btnModalClose.addEventListener('click', () => {
        window.soundManager?.playClick();
        this.closeModal();
      });
    }

    // Lives badge click
    const livesBadge = document.querySelector('.lives-badge');
    if (livesBadge) {
      livesBadge.addEventListener('click', () => {
        window.soundManager?.playClick();
        this.handleWatchAd();
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

        window.adManager.init(this.settings);

        this.renderUser();
        this.renderGames();
        this.startRegenTimer();
      }
    } catch (e) {
      console.error("Failed to load hub data:", e);
      this.showToast("Failed to connect to server.");
    }
  },

  renderUser() {
    if (!this.user) return;

    const avatarEl = document.getElementById('user-avatar');
    if (avatarEl) {
      const initial = (this.user.first_name || this.user.username || 'P')[0].toUpperCase();
      avatarEl.textContent = initial;
    }

    const usernameEl = document.getElementById('user-name');
    if (usernameEl) {
      usernameEl.textContent = this.user.first_name || this.user.username || 'Player';
    }

    const livesCountEl = document.getElementById('lives-count');
    if (livesCountEl) {
      const maxFree = this.user.max_free_lives || 3;
      livesCountEl.textContent = `${this.user.lives}/${maxFree}`;
    }

    this.updateRegenTimerUI();
  },

  startRegenTimer() {
    if (this.regenTimerInterval) clearInterval(this.regenTimerInterval);

    this.regenTimerInterval = setInterval(() => {
      const maxFree = this.user ? (this.user.max_free_lives || 3) : 3;
      if (this.user && this.user.lives < maxFree) {
        if (this.secondsUntilRegen > 0) {
          this.secondsUntilRegen--;
          this.updateRegenTimerUI();
        } else {
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

    const maxFree = this.user ? (this.user.max_free_lives || 3) : 3;
    if (!this.user || this.user.lives >= maxFree) {
      timerEl.textContent = this.user && this.user.lives > maxFree ? `Boosted (${this.user.lives} ❤️)` : 'Full ❤️';
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
      whack: 'icon-whack',
      space: 'icon-space',
      racer: 'icon-racer',
      breakout: 'icon-breakout'
    };

    const svgs = {
      snake: '<svg viewBox="0 0 24 24"><path d="M7 2a2 2 0 0 0-2 2v2a2 2 0 0 0 2 2h4v2H7a4 4 0 0 0-4 4v4a4 4 0 0 0 4 4h10a4 4 0 0 0 4-4v-4a4 4 0 0 0-4-4h-4V8h4a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H7zm11 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v4z"/></svg>',
      '2048': '<svg viewBox="0 0 24 24"><path d="M3 3v18h18V3H3zm16 16H5V5h14v14zM7 7h4v2H7V7zm6 0h4v6h-4V7zm-6 4h4v6H7v-6zm6 4h4v2h-4v-2z"/></svg>',
      flappy: '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 14h-2v-2h2v2zm0-4h-2V7h2v5z"/></svg>',
      tictactoe: '<svg viewBox="0 0 24 24"><path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm-9 14H6v-4h4v4zm0-6H6V7h4v4zm6 6h-4v-4h4v4zm0-6h-4V7h4v4z"/></svg>',
      memory: '<svg viewBox="0 0 24 24"><path d="M4 4h16v16H4V4zm2 2v12h12V6H6zm3 3h6v6H9V9z"/></svg>',
      whack: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8zm-1-5h2v2h-2zm0-8h2v6h-2z"/></svg>',
      space: '<svg viewBox="0 0 24 24"><path d="M12 2.5L7 8l2.5 1.5L12 6l2.5 3.5L17 8l-5-5.5zM6 10l-3 4 3 2 1.5-2L6 10zm12 0l-1.5 4 1.5 2 3-2-3-4zM12 9l-3 7h2v5h2v-5h2L12 9z"/></svg>',
      racer: '<svg viewBox="0 0 24 24"><path d="M18.92 6.01C18.72 5.42 18.16 5 17.5 5h-11c-.66 0-1.21.42-1.42 1.01L3 12v8c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h12v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-8l-2.08-5.99zM6.5 16c-.83 0-1.5-.67-1.5-1.5S5.67 13 6.5 13s1.5.67 1.5 1.5S7.33 16 6.5 16zm11 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zM5 11l1.5-4.5h11L19 11H5z"/></svg>',
      breakout: '<svg viewBox="0 0 24 24"><path d="M19 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 4h-4V6h4v2zm-6 0H9V6h4v2zm-6 0H5V6h2v2zm-2 4h4v2H5v-2zm6 0h4v2h-4v-2zm6 0h2v2h-2v-2zM5 18v-2h14v2H5z"/></svg>'
    };

    this.games.forEach(g => {
      const card = document.createElement('div');
      card.className = `game-card ${g.enabled ? '' : 'disabled'}`;
      card.innerHTML = `
        <div class="game-card-icon ${iconClasses[g.id] || ''}">
          ${svgs[g.id] || '🎮'}
        </div>
        <div class="game-card-title">${g.name.replace(/^[^\s]+\s/, '')}</div>
        <div class="game-card-score">Best: <span>${g.high_score || 0}</span></div>
        <button class="btn-play-game" data-id="${g.id}">
          ${g.enabled ? '▶ PLAY' : 'LOCKED'}
        </button>
      `;

      if (g.enabled) {
        card.addEventListener('click', () => {
          window.soundManager?.playClick();
          this.launchGame(g.id);
        });
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

    const startRes = await window.api.startGame(gameId);
    if (!startRes.success) {
      if (startRes.error === 'no_lives') {
        this.showNoLivesModal();
      } else {
        this.showToast(startRes.message || "Failed to start game.");
      }
      return;
    }

    if (startRes.lives !== undefined) {
      this.user.lives = startRes.lives;
      this.renderUser();
    }

    window.location.href = `/static/games/${gameId}/index.html`;
  },

  handleWatchAd() {
    window.tgApp?.hapticImpact('medium');
    window.adManager.showRewardedAd(
      (rewardRes) => {
        if (rewardRes.lives !== undefined) {
          this.user.lives = rewardRes.lives;
          this.secondsUntilRegen = rewardRes.seconds_until_regen || 0;
          this.renderUser();
        }
      },
      (errorMsg) => {
        if (errorMsg) this.showToast(errorMsg);
      }
    );
  },

  showNoLivesModal() {
    window.soundManager?.playGameOver();
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
