/**
 * 2048 Puzzle Logic
 */
const SIZE = 4;
let board = [];
let score = 0;
let highScore = 0;
let isGameOver = false;

function init() {
  window.gameBridge.init('2048');
  setupControls();
  resetGame();
}

function resetGame() {
  board = [
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0]
  ];
  score = 0;
  isGameOver = false;
  updateScoreUI();
  addRandomTile();
  addRandomTile();
  renderBoard();
}

function addRandomTile() {
  const emptyCells = [];
  for (let r = 0; r < SIZE; r++) {
    for (let c = 0; c < SIZE; c++) {
      if (board[r][c] === 0) {
        emptyCells.push({ r, c });
      }
    }
  }

  if (emptyCells.length > 0) {
    const randomCell = emptyCells[Math.floor(Math.random() * emptyCells.length)];
    board[randomCell.r][randomCell.c] = Math.random() < 0.9 ? 2 : 4;
  }
}

function renderBoard() {
  for (let r = 0; r < SIZE; r++) {
    for (let c = 0; c < SIZE; c++) {
      const cell = document.getElementById(`cell-${r}-${c}`);
      const val = board[r][c];
      cell.className = 'grid-cell';
      if (val > 0) {
        cell.textContent = val;
        cell.classList.add(`tile-${val}`);
      } else {
        cell.textContent = '';
      }
    }
  }
}

function slide(row) {
  let arr = row.filter(val => val !== 0);
  for (let i = 0; i < arr.length - 1; i++) {
    if (arr[i] === arr[i + 1]) {
      arr[i] *= 2;
      score += arr[i];
      arr.splice(i + 1, 1);
    }
  }
  while (arr.length < SIZE) {
    arr.push(0);
  }
  return arr;
}

function moveLeft() {
  let changed = false;
  for (let r = 0; r < SIZE; r++) {
    const oldRow = [...board[r]];
    board[r] = slide(board[r]);
    if (oldRow.some((val, i) => val !== board[r][i])) changed = true;
  }
  return changed;
}

function moveRight() {
  let changed = false;
  for (let r = 0; r < SIZE; r++) {
    const oldRow = [...board[r]];
    const reversed = [...board[r]].reverse();
    const slided = slide(reversed).reverse();
    board[r] = slided;
    if (oldRow.some((val, i) => val !== board[r][i])) changed = true;
  }
  return changed;
}

function moveUp() {
  let changed = false;
  for (let c = 0; c < SIZE; c++) {
    const col = [board[0][c], board[1][c], board[2][c], board[3][c]];
    const slided = slide(col);
    for (let r = 0; r < SIZE; r++) {
      if (board[r][c] !== slided[r]) changed = true;
      board[r][c] = slided[r];
    }
  }
  return changed;
}

function moveDown() {
  let changed = false;
  for (let c = 0; c < SIZE; c++) {
    const col = [board[0][c], board[1][c], board[2][c], board[3][c]].reverse();
    const slided = slide(col).reverse();
    for (let r = 0; r < SIZE; r++) {
      if (board[r][c] !== slided[r]) changed = true;
      board[r][c] = slided[r];
    }
  }
  return changed;
}

function handleMove(dir) {
  if (isGameOver) return;
  let moved = false;

  if (dir === 'left') moved = moveLeft();
  else if (dir === 'right') moved = moveRight();
  else if (dir === 'up') moved = moveUp();
  else if (dir === 'down') moved = moveDown();

  if (moved) {
    window.tgApp?.hapticImpact('light');
    addRandomTile();
    renderBoard();
    if (score > highScore) highScore = score;
    updateScoreUI();

    if (checkGameOver()) {
      triggerGameOver();
    }
  }
}

function checkGameOver() {
  // Check empty cells
  for (let r = 0; r < SIZE; r++) {
    for (let c = 0; c < SIZE; c++) {
      if (board[r][c] === 0) return false;
    }
  }
  // Check horizontal and vertical merges
  for (let r = 0; r < SIZE; r++) {
    for (let c = 0; c < SIZE; c++) {
      if (c < SIZE - 1 && board[r][c] === board[r][c + 1]) return false;
      if (r < SIZE - 1 && board[r][c] === board[r + 1][c]) return false;
    }
  }
  return true;
}

function triggerGameOver() {
  isGameOver = true;
  window.gameBridge.reportGameOver(score, 'lost', () => resetGame());
}

function updateScoreUI() {
  document.getElementById('score-display').textContent = score;
  document.getElementById('high-score-display').textContent = highScore;
}

function setupControls() {
  // Keyboard
  window.addEventListener('keydown', (e) => {
    switch (e.key) {
      case 'ArrowUp': case 'w': case 'W': handleMove('up'); break;
      case 'ArrowDown': case 's': case 'S': handleMove('down'); break;
      case 'ArrowLeft': case 'a': case 'A': handleMove('left'); break;
      case 'ArrowRight': case 'd': case 'D': handleMove('right'); break;
    }
  });

  // Touch Swipes
  const gridContainer = document.getElementById('grid-container');
  let startX = 0;
  let startY = 0;

  gridContainer.addEventListener('touchstart', (e) => {
    const t = e.touches[0];
    startX = t.clientX;
    startY = t.clientY;
  }, { passive: true });

  gridContainer.addEventListener('touchend', (e) => {
    const t = e.changedTouches[0];
    const dx = t.clientX - startX;
    const dy = t.clientY - startY;

    if (Math.abs(dx) > Math.abs(dy)) {
      if (dx > 30) handleMove('right');
      else if (dx < -30) handleMove('left');
    } else {
      if (dy > 30) handleMove('down');
      else if (dy < -30) handleMove('up');
    }
  }, { passive: true });
}

document.addEventListener('DOMContentLoaded', init);
