/**
 * Telegram WebApp SDK Integration & Helpers
 */
const tgApp = {
  tg: window.Telegram?.WebApp,
  isInsideTelegram: Boolean(window.Telegram?.WebApp?.initData),

  init() {
    if (this.tg) {
      this.tg.ready();
      this.tg.expand();
      try {
        this.tg.enableClosingConfirmation();
      } catch (e) {}

      // Set header / background colors
      if (this.tg.setHeaderColor) {
        this.tg.setHeaderColor('#0a0e17');
      }
      if (this.tg.setBackgroundColor) {
        this.tg.setBackgroundColor('#0a0e17');
      }
    }
  },

  getInitData() {
    return this.tg?.initData || '';
  },

  getUser() {
    if (this.tg?.initDataUnsafe?.user) {
      return this.tg.initDataUnsafe.user;
    }
    // Fallback for development browser testing
    return {
      id: 99999999,
      first_name: "Guest Player",
      username: "guest_player"
    };
  },

  hapticImpact(style = 'medium') {
    // style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'
    try {
      this.tg?.HapticFeedback?.impactOccurred(style);
    } catch (e) {}
  },

  hapticNotification(type = 'success') {
    // type: 'error' | 'success' | 'warning'
    try {
      this.tg?.HapticFeedback?.notificationOccurred(type);
    } catch (e) {}
  },

  hapticSelection() {
    try {
      this.tg?.HapticFeedback?.selectionChanged();
    } catch (e) {}
  },

  showBackButton(onClickCallback) {
    if (this.tg?.BackButton) {
      this.tg.BackButton.show();
      this.tg.BackButton.onClick(onClickCallback);
    }
  },

  hideBackButton() {
    if (this.tg?.BackButton) {
      this.tg.BackButton.hide();
    }
  }
};

window.tgApp = tgApp;
document.addEventListener('DOMContentLoaded', () => tgApp.init());
