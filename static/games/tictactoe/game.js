/**
 * Tic Tac Toe vs AI (Minimax Algorithm)
 */
let board = Array(9).fill('');
let currentPlayer = 'X'; // Human: X, AI: O
let difficulty = 'easy';
let isGameActive = true;
let wins = 0;
let losses = 0;
let draws = 0;

const WINNING_COMBOS = [
  [0, 1, 2], [3, 4, 5], [6, 7, 8], // Rows
  [0, 3, 6], [1, 4, 7], [2, 5, 8], // Cols
  [0, 4, 8], [2, 4, 6]             // Diagonals
];

function init() {
  window.gameBridge.init('tictactoe');
  setupControls();
  resetGame();
}

function resetGame() {
  board = Array(9).fill('');
  currentPlayer = 'X';
  isGameActive = true;
  updateStatus("Your Turn (❌)");
  renderBoard();
}

function renderBoard() {
  for (let i = 0; i < 9; i++) {
    const cell = document.querySelector(`.ttt-cell[data-idx="${i}"]`);
    cell.textContent = board[i];
    cell.className = `ttt-cell ${board[i].toLowerCase()}`;
  }
}

function updateStatus(text) {
  const statusEl = document.getElementById('status-banner');
  if (statusEl) statusEl.textContent = text;
}

function handleCellClick(index) {
  if (!isGameActive || board[index] !== '' || currentPlayer !== 'X') return;

  makeMove(index, 'X');
  window.tgApp?.hapticImpact('light');

  const winner = checkWinner(board);
  if (winner) {
    handleEndGame(winner);
    return;
  }

  if (board.every(cell => cell !== '')) {
    handleEndGame('draw');
    return;
  }

  // AI's turn
  currentPlayer = 'O';
  updateStatus("AI is thinking (⭕)...");

  setTimeout(() => {
    aiMove();
  }, 400);
}

function makeMove(index, player) {
  board[index] = player;
  renderBoard();
}

function aiMove() {
  if (!isGameActive) return;

  let chosenIndex;

  if (difficulty === 'easy') {
    chosenIndex = getRandomMove();
  } else if (difficulty === 'medium') {
    chosenIndex = Math.random() < 0.5 ? getBestMove() : getRandomMove();
  } else {
    // Master Minimax
    chosenIndex = getBestMove();
  }

  if (chosenIndex !== undefined && chosenIndex !== null) {
    makeMove(chosenIndex, 'O');
    window.tgApp?.hapticImpact('light');

    const winner = checkWinner(board);
    if (winner) {
      handleEndGame(winner);
      return;
    }

    if (board.every(cell => cell !== '')) {
      handleEndGame('draw');
      return;
    }

    currentPlayer = 'X';
    updateStatus("Your Turn (❌)");
  }
}

function getRandomMove() {
  const emptyIndices = board.map((val, idx) => val === '' ? idx : null).filter(val => val !== null);
  if (emptyIndices.length === 0) return null;
  return emptyIndices[Math.floor(Math.random() * emptyIndices.length)];
}

function getBestMove() {
  let bestScore = -Infinity;
  let move = null;

  for (let i = 0; i < 9; i++) {
    if (board[i] === '') {
      board[i] = 'O';
      let score = minimax(board, 0, false);
      board[i] = '';
      if (score > bestScore) {
        bestScore = score;
        move = i;
      }
    }
  }
  return move !== null ? move : getRandomMove();
}

function minimax(newBoard, depth, isMaximizing) {
  const winner = checkWinner(newBoard);
  if (winner === 'O') return 10 - depth;
  if (winner === 'X') return depth - 10;
  if (newBoard.every(cell => cell !== '')) return 0;

  if (isMaximizing) {
    let maxEval = -Infinity;
    for (let i = 0; i < 9; i++) {
      if (newBoard[i] === '') {
        newBoard[i] = 'O';
        let eval = minimax(newBoard, depth + 1, false);
        newBoard[i] = '';
        maxEval = Math.max(maxEval, eval);
      }
    }
    return maxEval;
  } else {
    let minEval = Infinity;
    for (let i = 0; i < 9; i++) {
      if (newBoard[i] === '') {
        newBoard[i] = 'X';
        let eval = minimax(newBoard, depth + 1, true);
        newBoard[i] = '';
        minEval = Math.min(minEval, eval);
      }
    }
    return minEval;
  }
}

function checkWinner(b) {
  for (let combo of WINNING_COMBOS) {
    const [a, bIdx, c] = combo;
    if (b[a] && b[a] === b[bIdx] && b[a] === b[c]) {
      return b[a];
    }
  }
  return null;
}

function handleEndGame(result) {
  isGameActive = false;

  if (result === 'X') {
    wins++;
    document.getElementById('wins-count').textContent = wins;
    updateStatus("🎉 You Won!");
    window.gameBridge.reportGameOver(wins * 100, 'won', () => resetGame());
  } else if (result === 'O') {
    losses++;
    document.getElementById('losses-count').textContent = losses;
    updateStatus("💀 AI Won!");
    window.gameBridge.reportGameOver(wins * 100, 'lost', () => resetGame());
  } else {
    draws++;
    document.getElementById('draws-count').textContent = draws;
    updateStatus("🤝 It's a Draw!");
    setTimeout(() => {
      resetGame();
    }, 1500);
  }
}

function setupControls() {
  document.querySelectorAll('.ttt-cell').forEach(cell => {
    cell.addEventListener('click', () => {
      const idx = parseInt(cell.dataset.idx);
      handleCellClick(idx);
    });
  });

  // Difficulty buttons
  document.querySelectorAll('.btn-diff').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.btn-diff').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      difficulty = btn.dataset.diff;
      window.tgApp?.hapticSelection();
      resetGame();
    });
  });
}

document.addEventListener('DOMContentLoaded', init);
