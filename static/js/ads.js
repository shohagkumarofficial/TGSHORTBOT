/**
 * Multi-Ad Network Manager (Adsgram, Monetag, Gigapub, Adsterra)
 * All networks show ads IN-APP (inside the mini app) via their own SDK overlays.
 * NO external page redirects. Each SDK returns a Promise:
 *   .then() = user watched ad fully → grant reward
 *   .catch() = user skipped/closed → no reward
 */
const adManager = {
  settings: {},
  adsgramController: null,
  isShowing: false,
  roundRobinIndex: 0,

  init(settings = {}) {
    this.settings = settings;

    // 1. Adsgram SDK
    if (this.isNetworkEnabled('adsgram') && window.Adsgram) {
      const blockId = settings.adsgram_block_id || '';
      if (blockId) {
        try {
          this.adsgramController = window.Adsgram.init({ blockId: blockId });
        } catch (e) {
          console.warn("Adsgram init error:", e);
        }
      }
    }

    // 2. Monetag TMA SDK — creates global show_ZONE_ID() function
    if (this.isNetworkEnabled('monetag') && settings.monetag_zone_id) {
      this.loadMonetagSDK(settings.monetag_zone_id);
    }

    // 3. Gigapub TMA SDK
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
    return networks.filter(net => this.isNetworkEnabled(net));
  },

  getNextNetwork() {
    const mode = this.settings.ad_selection_mode || 'round_robin';
    if (mode === 'single') {
      const selected = this.settings.selected_ad_network || 'adsgram';
      return this.isNetworkEnabled(selected) ? selected : this.getActiveNetworksList()[0] || 'adsgram';
    }

    const activeList = this.getActiveNetworksList();
    if (activeList.length === 0) return 'adsgram';
    const chosen = activeList[this.roundRobinIndex % activeList.length];
    this.roundRobinIndex = (this.roundRobinIndex + 1) % activeList.length;
    return chosen;
  },

  /**
   * Monetag TMA SDK Loader
   * Injects the official Monetag script tag which auto-creates window.show_ZONE_ID()
   * This function shows a rewarded interstitial INSIDE the mini app (overlay, no redirect)
   * and returns a Promise.
   */
  loadMonetagSDK(zoneId) {
    const cleanZone = zoneId.toString().trim();
    if (!cleanZone || document.getElementById('monetag-tma-sdk')) return;

    const script = document.createElement('script');
    script.id = 'monetag-tma-sdk';
    script.src = `https://alwingulla.com/88/tag.min.js`;
    script.setAttribute('data-zone', cleanZone);
    script.setAttribute('data-sdk', `show_${cleanZone}`);
    script.async = true;
    script.setAttribute('data-cfasync', 'false');
    document.head.appendChild(script);

    console.log(`[AdManager] Monetag TMA SDK loaded for zone: ${cleanZone}`);
  },

  /**
   * Gigapub TMA SDK Loader
   * Injects the Gigapub SDK which creates window.Gigapub or window.show_PROJECT_ID()
   */
  loadGigapubSDK(projectId) {
    const cleanId = projectId.toString().trim();
    if (!cleanId || document.getElementById('gigapub-tma-sdk')) return;

    const script = document.createElement('script');
    script.id = 'gigapub-tma-sdk';
    script.src = `https://gigapub.com/sdk.js`;
    script.setAttribute('data-project', cleanId);
    script.setAttribute('data-sdk', `show_${cleanId}`);
    script.async = true;
    document.head.appendChild(script);

    console.log(`[AdManager] Gigapub TMA SDK loaded for project: ${cleanId}`);
  },

  // =========================================================
  //  Main Entry Point: Show Rewarded Ad
  // =========================================================

  async showRewardedAd(onSuccess, onError) {
    if (this.isShowing) {
      if (onError) onError("Ad is already running. Please wait.");
      return;
    }

    const activeList = this.getActiveNetworksList();
    if (activeList.length === 0) {
      window.hub?.showToast("⚠️ No ad networks are enabled.");
      if (onError) onError("No networks enabled");
      return;
    }

    const targetNetwork = this.getNextNetwork();
    this.isShowing = true;
    window.hub?.showToast(`Loading ${targetNetwork.toUpperCase()} ad... 📺`);

    try {
      switch (targetNetwork) {
        case 'adsgram':
          await this._showAdsgram(onSuccess, onError);
          break;
        case 'monetag':
          await this._showMonetag(onSuccess, onError);
          break;
        case 'gigapub':
          await this._showGigapub(onSuccess, onError);
          break;
        case 'adsterra':
          await this._showAdsterra(onSuccess, onError);
          break;
        default:
          this.isShowing = false;
          if (onError) onError("Unknown network");
      }
    } catch (e) {
      this.isShowing = false;
      console.error(`[AdManager] ${targetNetwork} error:`, e);
      if (onError) onError(`${targetNetwork} ad failed`);
    }
  },

  // =========================================================
  //  1. ADSGRAM — In-App Rewarded Video
  //  SDK: window.Adsgram.init({blockId}).show() → Promise
  // =========================================================

  async _showAdsgram(onSuccess, onError) {
    const blockId = this.settings.adsgram_block_id || '';
    if (!blockId) {
      this.isShowing = false;
      window.hub?.showToast("⚠️ Adsgram Block ID not configured.");
      if (onError) onError("Adsgram Block ID missing");
      return;
    }

    try {
      if (!this.adsgramController && window.Adsgram) {
        this.adsgramController = window.Adsgram.init({ blockId: blockId });
      }

      if (!this.adsgramController) {
        this.isShowing = false;
        window.hub?.showToast("⚠️ Adsgram SDK not loaded.");
        if (onError) onError("Adsgram SDK unavailable");
        return;
      }

      // show() displays the ad INSIDE the mini app and returns a Promise
      await this.adsgramController.show();

      // If we reach here, user watched the ad fully
      this.isShowing = false;
      await this.claimReward('adsgram', onSuccess, onError);

    } catch (err) {
      // User closed/skipped the ad
      this.isShowing = false;
      console.warn("[AdManager] Adsgram ad not completed:", err);
      window.hub?.showToast("Ad closed before completion. No reward.");
      if (onError) onError(err?.description || "Ad closed");
    }
  },

  // =========================================================
  //  2. MONETAG — In-App Rewarded Interstitial
  //  SDK: window.show_ZONE_ID() → Promise
  //  Shows fullscreen ad overlay INSIDE the mini app (no redirect)
  // =========================================================

  async _showMonetag(onSuccess, onError) {
    const zoneId = (this.settings.monetag_zone_id || '').toString().trim();
    if (!zoneId) {
      this.isShowing = false;
      window.hub?.showToast("⚠️ Monetag Zone ID not configured.");
      if (onError) onError("Monetag Zone ID missing");
      return;
    }

    // The Monetag SDK auto-creates this global function when the script loads
    const showFnName = `show_${zoneId}`;
    const showFn = window[showFnName];

    if (typeof showFn !== 'function') {
      this.isShowing = false;
      console.warn(`[AdManager] Monetag function ${showFnName}() not found. SDK may still be loading.`);
      window.hub?.showToast("⚠️ Monetag ad is loading... Try again in a few seconds.");
      if (onError) onError("Monetag SDK not ready");
      return;
    }

    try {
      // show_ZONE_ID() displays the rewarded interstitial INSIDE the app
      // and returns a Promise that resolves when user finishes watching
      await showFn();

      // Promise resolved → user watched the ad fully inside the app
      this.isShowing = false;
      await this.claimReward('monetag', onSuccess, onError);

    } catch (err) {
      // Promise rejected → user skipped, closed, or ad failed to load
      this.isShowing = false;
      console.warn("[AdManager] Monetag ad not completed:", err);
      window.hub?.showToast("Ad closed before completion. No reward.");
      if (onError) onError("Monetag ad closed/failed");
    }
  },

  // =========================================================
  //  3. GIGAPUB — In-App Rewarded Ad
  //  SDK: window.show_PROJECT_ID() → Promise
  //  OR window.Gigapub.showRewarded() → Promise
  // =========================================================

  async _showGigapub(onSuccess, onError) {
    const projectId = (this.settings.gigapub_project_id || '').toString().trim();
    if (!projectId) {
      this.isShowing = false;
      window.hub?.showToast("⚠️ Gigapub Project ID not configured.");
      if (onError) onError("Gigapub Project ID missing");
      return;
    }

    // Try Method 1: Global show_PROJECT_ID() function (like Monetag pattern)
    const showFnName = `show_${projectId}`;
    const showFn = window[showFnName];

    if (typeof showFn === 'function') {
      try {
        await showFn();
        this.isShowing = false;
        await this.claimReward('gigapub', onSuccess, onError);
        return;
      } catch (err) {
        this.isShowing = false;
        console.warn("[AdManager] Gigapub ad not completed:", err);
        window.hub?.showToast("Ad closed before completion. No reward.");
        if (onError) onError("Gigapub ad closed/failed");
        return;
      }
    }

    // Try Method 2: window.Gigapub SDK object
    if (window.Gigapub || window.GigaPub) {
      const sdk = window.Gigapub || window.GigaPub;
      try {
        // Try showRewarded / showRewardedVideo / show
        const showMethod = sdk.showRewarded || sdk.showRewardedVideo || sdk.show;
        if (typeof showMethod === 'function') {
          await new Promise((resolve, reject) => {
            showMethod.call(sdk, {
              onRewarded: resolve,
              onReward: resolve,
              onSuccess: resolve,
              onError: reject,
              onClose: reject
            });
          });
          this.isShowing = false;
          await this.claimReward('gigapub', onSuccess, onError);
          return;
        }
      } catch (err) {
        this.isShowing = false;
        console.warn("[AdManager] Gigapub SDK ad not completed:", err);
        window.hub?.showToast("Ad closed before completion. No reward.");
        if (onError) onError("Gigapub ad closed/failed");
        return;
      }
    }

    // SDK not loaded yet
    this.isShowing = false;
    console.warn(`[AdManager] Gigapub function ${showFnName}() not found. SDK may still be loading.`);
    window.hub?.showToast("⚠️ Gigapub ad is loading... Try again in a few seconds.");
    if (onError) onError("Gigapub SDK not ready");
  },

  // =========================================================
  //  4. ADSTERRA — In-App Ad (similar SDK pattern)
  // =========================================================

  async _showAdsterra(onSuccess, onError) {
    const key = (this.settings.adsterra_key || '').toString().trim();
    if (!key) {
      this.isShowing = false;
      window.hub?.showToast("⚠️ Adsterra Key not configured.");
      if (onError) onError("Adsterra Key missing");
      return;
    }

    // Try show_KEY() pattern
    const showFn = window[`show_${key}`];
    if (typeof showFn === 'function') {
      try {
        await showFn();
        this.isShowing = false;
        await this.claimReward('adsterra', onSuccess, onError);
        return;
      } catch (err) {
        this.isShowing = false;
        window.hub?.showToast("Ad closed before completion. No reward.");
        if (onError) onError("Adsterra ad closed/failed");
        return;
      }
    }

    this.isShowing = false;
    window.hub?.showToast("⚠️ Adsterra ad is loading... Try again.");
    if (onError) onError("Adsterra SDK not ready");
  },

  // =========================================================
  //  Server-Side Reward Claim (Anti-Cheat Verified)
  // =========================================================

  async claimReward(network, onSuccess, onError) {
    try {
      const rewardRes = await window.api.claimAdReward(network);
      if (rewardRes.success) {
        window.soundManager?.playVictory();
        window.tgApp?.hapticNotification('success');
        window.hub?.showToast(rewardRes.message || "+1 ❤️ Life awarded!");
        if (onSuccess) onSuccess(rewardRes);
      } else {
        window.soundManager?.playGameOver();
        window.tgApp?.hapticNotification('error');
        window.hub?.showToast(rewardRes.message || "Failed to claim reward.");
        if (onError) onError(rewardRes.message);
      }
    } catch (e) {
      console.error("[AdManager] Reward claim network error:", e);
      if (onError) onError("Network error claiming reward");
    }
  }
};

window.adManager = adManager;
