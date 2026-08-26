/**
 * Memory Match Card Game Logic
 */
const EMOJIS = ['🚀', '⚡', '💎', '🔥', '👑', '🎯', '👾', '🌈'];

let cards = [];
let flippedCards = [];
let matchedPairs = 0;
let moves = 0;
let secondsElapsed = 0;
let timerInterval = null;
let isLocked = false;
let highScore = 0;

function init() {
  window.gameBridge.init('memory');
  resetGame();
}

function resetGame() {
  flippedCards = [];
  matchedPairs = 0;
  moves = 0;
  secondsElapsed = 0;
  isLocked = false;

  updateUI();
  startTimer();
  createBoard();
}

function startTimer() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    secondsElapsed++;
    const mins = Math.floor(secondsElapsed / 60).toString().padStart(2, '0');
    const secs = (secondsElapsed % 60).toString().padStart(2, '0');
    document.getElementById('timer-display').textContent = `${mins}:${secs}`;
  }, 1000);
}

function createBoard() {
  const grid = document.getElementById('memory-grid');
  grid.innerHTML = '';

  // Duplicate emojis to form pairs
  const deck = [...EMOJIS, ...EMOJIS];
  // Shuffle
  deck.sort(() => Math.random() - 0.5);

  deck.forEach((emoji, idx) => {
    const card = document.createElement('div');
    card.className = 'card';
    card.dataset.index = idx;
    card.dataset.emoji = emoji;

    card.innerHTML = `
      <div class="card-face card-front">❓</div>
      <div class="card-face card-back">${emoji}</div>
    `;

    card.addEventListener('click', () => handleCardClick(card));
    grid.appendChild(card);
  });
}

function handleCardClick(card) {
  if (isLocked || card.classList.contains('flipped') || card.classList.contains('matched')) {
    return;
  }

  card.classList.add('flipped');
  window.tgApp?.hapticImpact('light');
  flippedCards.push(card);

  if (flippedCards.length === 2) {
    moves++;
    updateUI();
    checkMatch();
  }
}

function checkMatch() {
  isLocked = true;
  const [card1, card2] = flippedCards;

  if (card1.dataset.emoji === card2.dataset.emoji) {
    // Matched!
    setTimeout(() => {
      card1.classList.add('matched');
      card2.classList.add('matched');
      flippedCards = [];
      matchedPairs++;
      window.tgApp?.hapticNotification('success');
      updateUI();
      isLocked = false;

      if (matchedPairs === EMOJIS.length) {
        handleVictory();
      }
    }, 300);
  } else {
    // Not a match
    setTimeout(() => {
      card1.classList.remove('flipped');
      card2.classList.remove('flipped');
      flippedCards = [];
      isLocked = false;
    }, 750);
  }
}

function handleVictory() {
  if (timerInterval) clearInterval(timerInterval);

  // Score formula: Higher is better, penalizes extra time and moves
  const finalScore = Math.max(100, Math.floor(5000 / (moves + secondsElapsed / 2)));
  if (finalScore > highScore) highScore = finalScore;

  window.gameBridge.reportGameOver(finalScore, 'won', () => resetGame());
}

function updateUI() {
  document.getElementById('moves-display').textContent = moves;
  document.getElementById('pairs-display').textContent = `${matchedPairs}/${EMOJIS.length}`;
}

document.addEventListener('DOMContentLoaded', init);
