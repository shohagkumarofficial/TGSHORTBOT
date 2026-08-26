/**
 * Whack-a-Mole Game Logic
 */
const holes = document.querySelectorAll('.hole');
const scoreDisplay = document.getElementById('score-display');
const comboDisplay = document.getElementById('combo-display');
const timeLeftDisplay = document.getElementById('time-left');
const startOverlay = document.getElementById('start-overlay');
const btnStart = document.getElementById('btn-start-whack');

let lastHole = null;
let timeUp = false;
let score = 0;
let combo = 1;
let timeLeft = 30;
let moleTimer = null;
let countdownTimer = null;
let highScore = 0;

function init() {
  window.gameBridge.init('whack');
  setupControls();
}

function randomTime(min, max) {
  return Math.round(Math.random() * (max - min) + min);
}

function randomHole(holes) {
  const idx = Math.floor(Math.random() * holes.length);
  const hole = holes[idx];
  if (hole === lastHole) {
    return randomHole(holes);
  }
  lastHole = hole;
  return hole;
}

function peep() {
  const time = randomTime(550, 950);
  const hole = randomHole(holes);
  hole.classList.add('up');
  hole.classList.remove('hit');

  moleTimer = setTimeout(() => {
    hole.classList.remove('up');
    if (!timeUp) peep();
  }, time);
}

function startGame() {
  score = 0;
  combo = 1;
  timeLeft = 30;
  timeUp = false;

  updateUI();
  if (startOverlay) startOverlay.style.display = 'none';

  peep();

  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    timeLeft--;
    updateUI();

    if (timeLeft <= 0) {
      clearInterval(countdownTimer);
      clearTimeout(moleTimer);
      timeUp = true;
      holes.forEach(h => h.classList.remove('up'));
      handleGameOver();
    }
  }, 1000);
}

function whack(e) {
  const hole = e.currentTarget.parentElement;
  if (!hole.classList.contains('up') || hole.classList.contains('hit')) return;

  hole.classList.add('hit');
  window.tgApp?.hapticImpact('medium');

  score += 10 * combo;
  combo = Math.min(5, combo + 1);
  updateUI();

  setTimeout(() => {
    hole.classList.remove('up');
  }, 150);
}

function handleGameOver() {
  window.tgApp?.hapticNotification('success');
  if (score > highScore) highScore = score;
  window.gameBridge.reportGameOver(score, 'completed', () => {
    if (startOverlay) startOverlay.style.display = 'flex';
  });
}

function updateUI() {
  if (scoreDisplay) scoreDisplay.textContent = score;
  if (comboDisplay) comboDisplay.textContent = `x${combo}`;
  if (timeLeftDisplay) timeLeftDisplay.textContent = `${timeLeft}s`;
}

function setupControls() {
  document.querySelectorAll('.mole').forEach(mole => {
    mole.addEventListener('pointerdown', whack);
  });

  if (btnStart) {
    btnStart.addEventListener('click', startGame);
  }
}

document.addEventListener('DOMContentLoaded', init);
