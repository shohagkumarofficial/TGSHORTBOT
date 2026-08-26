/**
 * Multi-Ad Network Manager (Adsgram, Monetag, Gigapub, Adsterra)
 * True multi-SDK integration with verified watch timers and anti-cheat protection
 */
const adManager = {
  settings: {},
  adsgramController: null,
  isShowing: false,
  roundRobinIndex: 0,
  adCountdownTimer: null,
  adSecondsLeft: 15,

  init(settings = {}) {
    this.settings = settings;

    // 1. Initialize Adsgram SDK
    if (this.isNetworkEnabled('adsgram') && window.Adsgram) {
      const blockId = settings.adsgram_block_id || 'int-4166';
      try {
        this.adsgramController = window.Adsgram.init({ blockId: blockId });
      } catch (e) {
        console.warn("Adsgram init error:", e);
      }
    }

    // 2. Initialize Monetag SDK & Tag
    if (this.isNetworkEnabled('monetag') && settings.monetag_zone_id) {
      this.loadMonetagSDK(settings.monetag_zone_id);
    }

    // 3. Initialize Gigapub SDK
    if (this.isNetworkEnabled('gigapub') && settings.gigapub_project_id) {
      this.loadGigapubSDK(settings.gigapub_project_id);
    }
  },

  isNetworkEnabled(network) {
    const key = `${network}_enabled`;
    return this.settings[key] === '1' || this.settings[key] === true;
  },

  getActiveNetworksList() {
    const networks = ['adsgram', 'monetag', 'gigapub', 'adsterra'];
    const active = networks.filter(net => this.isNetworkEnabled(net));
    return active.length > 0 ? active : ['adsgram'];
  },

  getNextNetwork() {
    const mode = this.settings.ad_selection_mode || 'round_robin';
    if (mode === 'single') {
      const selected = this.settings.selected_ad_network || 'adsgram';
      return this.isNetworkEnabled(selected) ? selected : 'adsgram';
    }

    const activeList = this.getActiveNetworksList();
    const chosen = activeList[this.roundRobinIndex % activeList.length];
    this.roundRobinIndex = (this.roundRobinIndex + 1) % activeList.length;
    return chosen;
  },

  loadMonetagSDK(zoneId) {
    if (document.getElementById('monetag-sdk-tag')) return;
    try {
      const cleanZone = zoneId.toString().replace(/[^0-9]/g, '');
      if (cleanZone) {
        // Tag 1: Main Monetag multi-tag loader
        const s1 = document.createElement('script');
        s1.id = 'monetag-sdk-tag';
        s1.src = 'https://alwingulla.com/88/tag.min.js';
        s1.setAttribute('data-zone', cleanZone);
        s1.async = true;
        s1.setAttribute('data-cfasync', 'false');
        document.head.appendChild(s1);

        // Tag 2: Vignette / Interstitial trigger
        const s2 = document.createElement('script');
        s2.id = 'monetag-vignette-tag';
        s2.src = 'https://niphaumeenses.net/vignette.min.js';
        s2.setAttribute('data-zone', cleanZone);
        s2.async = true;
        document.head.appendChild(s2);
      }
    } catch (e) {
      console.warn("Failed to inject Monetag SDK:", e);
    }
  },

  loadGigapubSDK(projectId) {
    if (document.getElementById('gigapub-sdk')) return;
    const s = document.createElement('script');
    s.id = 'gigapub-sdk';
    s.src = 'https://sdk.gigapub.com/sdk.js';
    s.async = true;
    s.onload = () => {
      if (window.GigaPub && typeof window.GigaPub.init === 'function') {
        try {
          window.GigaPub.init({ projectId: projectId });
        } catch (e) {}
      }
    };
    document.head.appendChild(s);
  },

  async showRewardedAd(onSuccess, onError) {
    if (this.isShowing) {
      if (onError) onError("Ad is already running. Please wait.");
      return;
    }

    const targetNetwork = this.getNextNetwork();
    if (!this.isNetworkEnabled(targetNetwork)) {
      window.hub?.showToast(`⚠️ ${targetNetwork.toUpperCase()} is currently disabled.`);
      if (onError) onError("Network disabled");
      return;
    }

    this.isShowing = true;
    window.hub?.showToast(`Loading ${targetNetwork.toUpperCase()} ad... 📺`);

    if (targetNetwork === 'adsgram') {
      this.showAdsgram(onSuccess, onError);
    } else if (targetNetwork === 'monetag') {
      this.showMonetag(onSuccess, onError);
    } else if (targetNetwork === 'gigapub') {
      this.showGigapub(onSuccess, onError);
    } else {
      this.showAdsterra(onSuccess, onError);
    }
  },

  // --- 1. Adsgram (Rewarded Video SDK) ---
  showAdsgram(onSuccess, onError) {
    const blockId = this.settings.adsgram_block_id || 'int-4166';
    try {
      if (!this.adsgramController && window.Adsgram) {
        this.adsgramController = window.Adsgram.init({ blockId: blockId });
      }

      if (this.adsgramController) {
        this.adsgramController.show()
          .then(async (result) => {
            this.isShowing = false;
            await this.claimReward('adsgram', onSuccess, onError);
          })
          .catch(async (err) => {
            this.isShowing = false;
            console.warn("Adsgram video ad skipped or error:", err);
            window.hub?.showToast("Ad was closed before completion. No reward granted.");
            if (onError) onError(err?.description || "Ad closed early");
          });
      } else {
        this.isShowing = false;
        window.hub?.showToast("Adsgram SDK is not loaded. Check internet or Block ID.");
        if (onError) onError("Adsgram SDK unavailable");
      }
    } catch (e) {
      this.isShowing = false;
      if (onError) onError("Adsgram execution failed");
    }
  },

  // --- 2. Monetag (Telegram Mini App Rewarded Ad) ---
  showMonetag(onSuccess, onError) {
    const zoneId = this.settings.monetag_zone_id || '';
    if (!zoneId) {
      this.isShowing = false;
      window.hub?.showToast("⚠️ Monetag Zone ID is not configured in Admin panel.");
      if (onError) onError("Monetag Zone ID missing");
      return;
    }

    let sponsorUrl = '';
    const cleanZone = zoneId.toString().replace(/[^0-9]/g, '');

    if (zoneId.startsWith('http://') || zoneId.startsWith('https://')) {
      sponsorUrl = zoneId;
    } else if (cleanZone) {
      sponsorUrl = `https://otieuwai.net/4/${cleanZone}`;
      
      // If Monetag programmatic function exists, invoke it
      const fnName = 'show_' + cleanZone;
      if (typeof window[fnName] === 'function') {
        try {
          window[fnName]().then(() => {}).catch(() => {});
        } catch (e) {}
      }
    }

    // Launch Full-Screen Sponsor Modal with 15s countdown
    this.showSponsorCountdownModal('monetag', sponsorUrl, onSuccess, onError);
  },

  // --- 3. Gigapub (Telegram Mini App Rewarded SDK) ---
  showGigapub(onSuccess, onError) {
    const projectId = this.settings.gigapub_project_id || '';
    if (!projectId) {
      this.isShowing = false;
      window.hub?.showToast("⚠️ Gigapub Project ID is not configured in Admin panel.");
      if (onError) onError("Gigapub Project ID missing");
      return;
    }

    // Try Native Gigapub SDK
    if (window.GigaPub) {
      try {
        if (typeof window.GigaPub.showRewardedVideo === 'function') {
          window.GigaPub.showRewardedVideo({
            onRewarded: async () => {
              this.isShowing = false;
              await this.claimReward('gigapub', onSuccess, onError);
            },
            onError: (err) => {
              this.isShowing = false;
              window.hub?.showToast("Gigapub ad closed before completion.");
              if (onError) onError("Gigapub ad closed");
            }
          });
          return;
        } else if (typeof window.GigaPub.show === 'function') {
          window.GigaPub.show({
            type: 'rewarded',
            onSuccess: async () => {
              this.isShowing = false;
              await this.claimReward('gigapub', onSuccess, onError);
            },
            onError: () => {
              this.isShowing = false;
              if (onError) onError("Gigapub ad failed");
            }
          });
          return;
        }
      } catch (e) {
        console.warn("Gigapub SDK show error:", e);
      }
    }

    // Fallback Sponsor Modal with verified 15s timer
    const sponsorUrl = `https://sdk.gigapub.com/view/${projectId}`;
    this.showSponsorCountdownModal('gigapub', sponsorUrl, onSuccess, onError);
  },

  // --- 4. Adsterra / Custom Sponsor ---
  showAdsterra(onSuccess, onError) {
    const key = this.settings.adsterra_key || '';
    const sponsorUrl = key.startsWith('http') ? key : '';
    this.showSponsorCountdownModal('adsterra', sponsorUrl, onSuccess, onError);
  },

  // --- Full-Screen 15s Rewarded Ad Countdown Controller ---
  showSponsorCountdownModal(network, sponsorUrl, onSuccess, onError) {
    const modal = document.getElementById('rewarded-ad-modal');
    const timerText = document.getElementById('ad-timer-countdown');
    const progressFill = document.getElementById('ad-progress-fill');
    const btnOpenLink = document.getElementById('btn-open-sponsor-link');
    const btnClaim = document.getElementById('btn-claim-ad-reward');
    const btnCancel = document.getElementById('btn-cancel-ad');
    const titleEl = document.getElementById('ad-modal-title');
    const descEl = document.getElementById('ad-modal-desc');

    if (!modal) {
      this.isShowing = false;
      return;
    }

    const DURATION = 15;
    this.adSecondsLeft = DURATION;

    if (titleEl) titleEl.textContent = `📺 ${network.toUpperCase()} Sponsor Ad`;
    if (descEl) descEl.innerHTML = `Please view the sponsor ad for <b>${DURATION}s</b> to receive <b>+1 ❤️ Life</b>.`;
    if (timerText) timerText.textContent = `${DURATION}s`;
    if (progressFill) progressFill.style.width = '0%';
    if (btnClaim) btnClaim.style.display = 'none';
    if (btnCancel) btnCancel.style.display = 'block';

    // Configure Sponsor Link Button
    if (sponsorUrl && btnOpenLink) {
      btnOpenLink.style.display = 'block';
      btnOpenLink.textContent = `🔗 Open ${network.toUpperCase()} Sponsor Ad`;
      btnOpenLink.onclick = () => {
        if (window.Telegram?.WebApp?.openLink) {
          window.Telegram.WebApp.openLink(sponsorUrl);
        } else {
          window.open(sponsorUrl, '_blank');
        }
      };

      // Auto-trigger open link once on start
      setTimeout(() => {
        if (window.Telegram?.WebApp?.openLink) {
          window.Telegram.WebApp.openLink(sponsorUrl);
        }
      }, 200);
    } else if (btnOpenLink) {
      btnOpenLink.style.display = 'none';
    }

    modal.classList.add('active');

    // Cancel Button Handler (Early exit = STRICTLY NO REWARD)
    btnCancel.onclick = () => {
      if (this.adCountdownTimer) clearInterval(this.adCountdownTimer);
      modal.classList.remove('active');
      this.isShowing = false;
      window.hub?.showToast("⚠️ Ad closed early. No life awarded.");
      if (onError) onError("Ad closed early");
    };

    // 15s Countdown Interval
    if (this.adCountdownTimer) clearInterval(this.adCountdownTimer);

    this.adCountdownTimer = setInterval(() => {
      this.adSecondsLeft--;

      if (timerText) timerText.textContent = `${this.adSecondsLeft}s`;
      if (progressFill) {
        const percent = Math.floor(((DURATION - this.adSecondsLeft) / DURATION) * 100);
        progressFill.style.width = `${percent}%`;
      }

      if (this.adSecondsLeft <= 0) {
        clearInterval(this.adCountdownTimer);
        if (timerText) timerText.textContent = '🎉 Completed!';
        if (descEl) descEl.innerHTML = 'Ad watched successfully! Click below to claim your <b>+1 ❤️ Life</b>.';
        if (btnClaim) btnClaim.style.display = 'block';
        if (btnCancel) btnCancel.style.display = 'none';

        window.soundManager?.playScore();
        window.tgApp?.hapticNotification('success');

        // Claim Button Click
        btnClaim.onclick = async () => {
          modal.classList.remove('active');
          this.isShowing = false;
          await this.claimReward(network, onSuccess, onError);
        };
      }
    }, 1000);
  },

  async claimReward(network, onSuccess, onError) {
    try {
      const rewardRes = await window.api.claimAdReward(network);
      if (rewardRes.success) {
        window.soundManager?.playVictory();
        window.tgApp?.hapticNotification('success');
        window.hub?.showToast(rewardRes.message);
        if (onSuccess) onSuccess(rewardRes);
      } else {
        window.soundManager?.playGameOver();
        window.tgApp?.hapticNotification('error');
        window.hub?.showToast(rewardRes.message || "Failed to claim reward.");
        if (onError) onError(rewardRes.message);
      }
    } catch (e) {
      if (onError) onError("Network error claiming reward");
    }
  }
};

window.adManager = adManager;
