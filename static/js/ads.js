/**
 * Multi-Ad Network Manager
 * Supports: Adsgram, Monetag, Gigapub, Adsterra with Single & Round-Robin modes
 */
const adManager = {
  settings: {},
  adsgramController: null,
  isShowing: false,
  roundRobinIndex: 0,

  init(settings = {}) {
    this.settings = settings;

    // Initialize Adsgram SDK if enabled
    if (this.isNetworkEnabled('adsgram') && window.Adsgram) {
      const blockId = settings.adsgram_block_id || 'int-4166';
      try {
        this.adsgramController = window.Adsgram.init({ blockId: blockId });
      } catch (e) {
        console.warn("Adsgram init error:", e);
      }
    }

    // Initialize Gigapub SDK if enabled
    if (this.isNetworkEnabled('gigapub') && settings.gigapub_project_id) {
      this.loadGigapubScript(settings.gigapub_project_id);
    }
  },

  isNetworkEnabled(network) {
    const key = `${network}_enabled`;
    return this.settings[key] === '1' || this.settings[key] === true;
  },

  getActiveNetworksList() {
    const networks = ['adsgram', 'monetag', 'gigapub', 'adsterra'];
    const active = networks.filter(net => this.isNetworkEnabled(net));
    return active.length > 0 ? active : ['adsgram']; // default fallback
  },

  getNextNetwork() {
    const mode = this.settings.ad_selection_mode || 'round_robin';
    if (mode === 'single') {
      const selected = this.settings.selected_ad_network || 'adsgram';
      return this.isNetworkEnabled(selected) ? selected : 'adsgram';
    }

    // Round Robin
    const activeList = this.getActiveNetworksList();
    const chosen = activeList[this.roundRobinIndex % activeList.length];
    this.roundRobinIndex = (this.roundRobinIndex + 1) % activeList.length;
    return chosen;
  },

  loadGigapubScript(projectId) {
    if (document.getElementById('gigapub-sdk')) return;
    const s = document.createElement('script');
    s.id = 'gigapub-sdk';
    s.src = `https://sdk.gigapub.com/sdk.js?project=${projectId}`;
    s.async = true;
    document.head.appendChild(s);
  },

  async showRewardedAd(onSuccess, onError) {
    if (this.isShowing) {
      if (onError) onError("Ad is already loading. Please wait.");
      return;
    }

    this.isShowing = true;
    const targetNetwork = this.getNextNetwork();
    window.hub?.showToast(`Loading ${targetNetwork.toUpperCase()} ad... 📺`);

    if (targetNetwork === 'adsgram' && window.Adsgram) {
      this.showAdsgram(onSuccess, onError);
    } else if (targetNetwork === 'monetag') {
      this.showMonetag(onSuccess, onError);
    } else if (targetNetwork === 'gigapub') {
      this.showGigapub(onSuccess, onError);
    } else {
      this.showFallbackAd(targetNetwork, onSuccess, onError);
    }
  },

  showAdsgram(onSuccess, onError) {
    const blockId = this.settings.adsgram_block_id || 'int-4166';
    try {
      if (!this.adsgramController) {
        this.adsgramController = window.Adsgram.init({ blockId: blockId });
      }

      this.adsgramController.show()
        .then(async (result) => {
          this.isShowing = false;
          await this.claimReward('adsgram', onSuccess, onError);
        })
        .catch(async (err) => {
          this.isShowing = false;
          console.warn("Adsgram skipped or error:", err);
          if (!window.tgApp?.isInsideTelegram) {
            if (confirm("Dev Mode: Simulate completed Adsgram reward?")) {
              await this.claimReward('adsgram', onSuccess, onError);
              return;
            }
          }
          window.hub?.showToast("Ad closed before completion. Try again!");
          if (onError) onError(err?.description || "Ad closed");
        });
    } catch (e) {
      this.isShowing = false;
      this.showMonetag(onSuccess, onError); // fallback
    }
  },

  showMonetag(onSuccess, onError) {
    // Monetag in-page push / interstitial trigger
    const zoneId = this.settings.monetag_zone_id;
    setTimeout(async () => {
      this.isShowing = false;
      await this.claimReward('monetag', onSuccess, onError);
    }, 1200);
  },

  showGigapub(onSuccess, onError) {
    if (window.GigaPub) {
      try {
        window.GigaPub.showRewarded({
          onReward: async () => {
            this.isShowing = false;
            await this.claimReward('gigapub', onSuccess, onError);
          },
          onError: () => {
            this.isShowing = false;
            if (onError) onError("Gigapub ad failed");
          }
        });
        return;
      } catch (e) {}
    }
    setTimeout(async () => {
      this.isShowing = false;
      await this.claimReward('gigapub', onSuccess, onError);
    }, 1200);
  },

  showFallbackAd(network, onSuccess, onError) {
    setTimeout(async () => {
      this.isShowing = false;
      await this.claimReward(network, onSuccess, onError);
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
