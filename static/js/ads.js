/**
 * Rewarded Ad Manager (Adsgram & Monetag Integration)
 */
const adManager = {
  adsgramController: null,
  adsgramBlockId: 'int-4166',
  monetagZoneId: '',
  activeNetwork: 'both',
  isShowing: false,

  init(settings = {}) {
    if (settings.adsgram_block_id) {
      this.adsgramBlockId = settings.adsgram_block_id;
    }
    if (settings.monetag_zone_id) {
      this.monetagZoneId = settings.monetag_zone_id;
    }
    if (settings.active_ad_network) {
      this.activeNetwork = settings.active_ad_network;
    }

    // Initialize Adsgram SDK controller
    if (window.Adsgram && this.adsgramBlockId) {
      try {
        this.adsgramController = window.Adsgram.init({ blockId: this.adsgramBlockId });
      } catch (e) {
        console.warn("Failed to initialize Adsgram controller:", e);
      }
    }
  },

  async showRewardedAd(onSuccess, onError) {
    if (this.isShowing) {
      if (onError) onError("Ad is already loading. Please wait.");
      return;
    }

    this.isShowing = true;
    window.hub?.showToast("Loading rewarded ad... 📺");

    // Determine network
    const network = (this.activeNetwork === 'monetag') ? 'monetag' : 'adsgram';

    if (network === 'adsgram' && window.Adsgram) {
      try {
        if (!this.adsgramController) {
          this.adsgramController = window.Adsgram.init({ blockId: this.adsgramBlockId });
        }

        this.adsgramController.show()
          .then(async (result) => {
            this.isShowing = false;
            // User successfully watched ad
            const rewardRes = await window.api.claimAdReward('adsgram');
            if (rewardRes.success) {
              window.tgApp?.hapticNotification('success');
              window.hub?.showToast(rewardRes.message);
              if (onSuccess) onSuccess(rewardRes);
            } else {
              window.tgApp?.hapticNotification('error');
              window.hub?.showToast(rewardRes.message || "Failed to claim reward.");
              if (onError) onError(rewardRes.message);
            }
          })
          .catch(async (err) => {
            this.isShowing = false;
            console.warn("Adsgram error or skipped:", err);
            // If Adsgram failed or in development environment, allow simulated reward for testing
            if (!window.tgApp?.isInsideTelegram) {
              const confirmMock = confirm("Development Mode: Simulate completed rewarded ad (+1 Life)?");
              if (confirmMock) {
                const rewardRes = await window.api.claimAdReward('adsgram');
                if (rewardRes.success) {
                  window.hub?.showToast(rewardRes.message);
                  if (onSuccess) onSuccess(rewardRes);
                  return;
                }
              }
            }
            window.hub?.showToast("Ad was skipped or unavailable. Try again!");
            if (onError) onError(err?.description || "Ad closed before completion");
          });
      } catch (e) {
        this.isShowing = false;
        console.error("Adsgram show error:", e);
        if (onError) onError("Failed to load ad.");
      }
    } else {
      // Monetag or Fallback
      setTimeout(async () => {
        this.isShowing = false;
        const rewardRes = await window.api.claimAdReward(network);
        if (rewardRes.success) {
          window.tgApp?.hapticNotification('success');
          window.hub?.showToast(rewardRes.message);
          if (onSuccess) onSuccess(rewardRes);
        } else {
          window.hub?.showToast(rewardRes.message);
          if (onError) onError(rewardRes.message);
        }
      }, 1000);
    }
  }
};

window.adManager = adManager;
