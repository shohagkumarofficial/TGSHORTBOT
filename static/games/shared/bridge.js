/**
 * Unified Game Bridge: connects standalone HTML5 games to the Life & Monetization backend
 */
const gameBridge = {
  gameId: '',
  user: null,
  highScore: 0,
  onRestartCallback: null,

  async init(gameId) {
    this.gameId = gameId;
    this.ensureRewardedAdModalExists();

    // Telegram back button
    window.tgApp?.showBackButton(() => {
      window.soundManager?.playClick();
      this.returnToHub();
    });

    // Back to hub button in HUD
    const backBtn = document.getElementById('btn-back-hud');
    if (backBtn) {
      backBtn.addEventListener('click', () => {
        window.soundManager?.playClick();
        this.returnToHub();
      });
    }

    // Sound toggle button in HUD
    const soundBtn = document.getElementById('btn-sound-hud');
    if (soundBtn) {
      soundBtn.addEventListener('click', () => {
        window.soundManager?.toggleMute();
      });
    }

    // Modal buttons
    const goHubBtn = document.getElementById('btn-go-hub');
    if (goHubBtn) {
      goHubBtn.addEventListener('click', () => {
        window.soundManager?.playClick();
        this.returnToHub();
      });
    }

    const goPlayBtn = document.getElementById('btn-go-play');
    if (goPlayBtn) {
      goPlayBtn.addEventListener('click', () => {
        window.soundManager?.playClick();
        this.handleRestart();
      });
    }

    const goAdBtn = document.getElementById('btn-go-ad');
    if (goAdBtn) {
      goAdBtn.addEventListener('click', () => {
        window.soundManager?.playClick();
        this.handleWatchAdGameOver();
      });
    }

    // Fetch initial user state
    try {
      const data = await window.api.getUserInfo();
      if (data && data.success) {
        this.user = data.user;
        this.highScore = data.high_scores[gameId] || 0;
        window.adManager.init(data.settings);
        this.updateLivesHUD();
      }
    } catch (e) {
      console.warn("Could not fetch user in game bridge:", e);
    }
  },

  ensureRewardedAdModalExists() {
    if (document.getElementById('rewarded-ad-modal')) return;

    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'rewarded-ad-modal';
    modal.innerHTML = `
      <div class="modal-card">
        <div class="modal-icon" id="ad-modal-icon">📺</div>
        <h3 class="modal-title" id="ad-modal-title">Sponsor Ad Playing</h3>
        <p class="modal-desc" id="ad-modal-desc">
          Please wait for the timer to finish to unlock your <b>+1 ❤️ Life</b> reward.
        </p>

        <div class="ad-timer-container">
          <div class="ad-timer-text" id="ad-timer-countdown">15s</div>
          <div class="ad-progress-bar-bg">
            <div class="ad-progress-bar-fill" id="ad-progress-fill"></div>
          </div>
        </div>

        <div class="modal-actions" style="margin-top: 16px;">
          <button class="btn-primary-action" id="btn-open-sponsor-link" style="display: none; background: linear-gradient(135deg, #00f2fe, #4facfe);">
            🔗 Click to Open Sponsor Ad
          </button>
          <button class="btn-primary-action" id="btn-claim-ad-reward" style="display: none; background: linear-gradient(135deg, #2ed573, #7bed9f); color: #000;">
            🎉 Claim +1 ❤️ Life
          </button>
          <button class="btn-secondary-action" id="btn-cancel-ad">
            ❌ Close (Cancel Reward)
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  },

  updateLivesHUD() {
    const livesEl = document.getElementById('hud-lives-count');
    if (livesEl && this.user) {
      const maxFree = this.user.max_free_lives || 3;
      livesEl.textContent = `${this.user.lives}/${maxFree}`;
    }
  },

  returnToHub() {
    window.location.href = '/';
  },

  async reportGameOver(score, result = 'lost', onRestart = null) {
    this.onRestartCallback = onRestart;
    
    if (result === 'won' || result === 'completed') {
      window.soundManager?.playVictory();
      window.tgApp?.hapticNotification('success');
    } else {
      window.soundManager?.playGameOver();
      window.tgApp?.hapticNotification('error');
    }

    let currentLives = this.user ? this.user.lives : 0;
    let high = this.highScore;

    try {
      const res = await window.api.endGame(this.gameId, score, result);
      if (res && res.success) {
        currentLives = res.lives;
        high = res.high_score;
        if (this.user) this.user.lives = currentLives;
        this.updateLivesHUD();
      }
    } catch (e) {
      console.error("Failed to report game over:", e);
    }

    // Show Game Over Dialog
    const dialog = document.getElementById('game-over-dialog');
    const scoreVal = document.getElementById('go-score-val');
    const highVal = document.getElementById('go-high-val');
    const livesRemain = document.getElementById('go-lives-val');
    const playBtn = document.getElementById('btn-go-play');
    const adBtn = document.getElementById('btn-go-ad');
    const emojiEl = document.getElementById('go-emoji');
    const titleEl = document.getElementById('go-title');

    if (scoreVal) scoreVal.textContent = score;
    if (highVal) highVal.textContent = high;
    if (livesRemain) livesRemain.textContent = `${currentLives} Lives Remaining`;

    if (result === 'won' || result === 'completed') {
      if (emojiEl) emojiEl.textContent = '🎉';
      if (titleEl) titleEl.textContent = 'Awesome Game!';
    } else {
      if (emojiEl) emojiEl.textContent = '💀';
      if (titleEl) titleEl.textContent = 'Game Over';
    }

    if (currentLives <= 0) {
      if (playBtn) playBtn.style.display = 'none';
      if (adBtn) adBtn.style.display = 'block';
    } else {
      if (playBtn) playBtn.style.display = 'block';
      if (adBtn) adBtn.style.display = 'none';
    }

    if (dialog) dialog.classList.add('active');
  },

  async handleRestart() {
    const dialog = document.getElementById('game-over-dialog');
    
    const startRes = await window.api.startGame(this.gameId);
    if (!startRes.success) {
      if (startRes.error === 'no_lives') {
        const playBtn = document.getElementById('btn-go-play');
        const adBtn = document.getElementById('btn-go-ad');
        if (playBtn) playBtn.style.display = 'none';
        if (adBtn) adBtn.style.display = 'block';
      }
      return;
    }

    if (startRes.lives !== undefined && this.user) {
      this.user.lives = startRes.lives;
      this.updateLivesHUD();
    }

    if (dialog) dialog.classList.remove('active');

    if (this.onRestartCallback) {
      this.onRestartCallback();
    } else {
      window.location.reload();
    }
  },

  handleWatchAdGameOver() {
    window.adManager.showRewardedAd(
      (rewardRes) => {
        if (rewardRes.lives !== undefined && this.user) {
          this.user.lives = rewardRes.lives;
          this.updateLivesHUD();
        }
        this.handleRestart();
      },
      (err) => {
        console.warn("Ad skipped in game over:", err);
      }
    );
  }
};

window.gameBridge = gameBridge;
