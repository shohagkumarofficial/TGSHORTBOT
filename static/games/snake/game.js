/**
 * Snake Game Logic
 */
const canvas = document.getElementById('game-canvas');
const ctx = canvas.getContext('2d');

const GRID_SIZE = 17;
const CELL_SIZE = 20; // 17 * 20 = 340px

let snake = [];
let direction = { x: 1, y: 0 };
let nextDirection = { x: 1, y: 0 };
let food = { x: 5, y: 5 };
let score = 0;
let highScore = 0;
let isGameOver = false;
let gameLoopInterval = null;
let particles = [];

function init() {
  window.gameBridge.init('snake');
  setupControls();
  resetGame();
}

function resetGame() {
  snake = [
    { x: 5, y: 8 },
    { x: 4, y: 8 },
    { x: 3, y: 8 }
  ];
  direction = { x: 1, y: 0 };
  nextDirection = { x: 1, y: 0 };
  score = 0;
  isGameOver = false;
  particles = [];
  updateScoreUI();
  spawnFood();

  if (gameLoopInterval) clearInterval(gameLoopInterval);
  gameLoopInterval = setInterval(gameStep, 110);
}

function spawnFood() {
  let valid = false;
  while (!valid) {
    food = {
      x: Math.floor(Math.random() * GRID_SIZE),
      y: Math.floor(Math.random() * GRID_SIZE)
    };
    valid = !snake.some(s => s.x === food.x && s.y === food.y);
  }
}

function gameStep() {
  if (isGameOver) return;

  // Update direction
  direction = { ...nextDirection };

  // Calculate new head
  const head = {
    x: snake[0].x + direction.x,
    y: snake[0].y + direction.y
  };

  // Wall collisions
  if (head.x < 0 || head.x >= GRID_SIZE || head.y < 0 || head.y >= GRID_SIZE) {
    triggerGameOver();
    return;
  }

  // Self collisions
  if (snake.some(segment => segment.x === head.x && segment.y === head.y)) {
    triggerGameOver();
    return;
  }

  snake.unshift(head);

  // Check food
  if (head.x === food.x && head.y === food.y) {
    score += 10;
    if (score > highScore) highScore = score;
    updateScoreUI();
    window.tgApp?.hapticImpact('light');
    createParticles(head.x * CELL_SIZE + 10, head.y * CELL_SIZE + 10);
    spawnFood();
  } else {
    snake.pop();
  }

  draw();
}

function createParticles(x, y) {
  for (let i = 0; i < 8; i++) {
    particles.push({
      x, y,
      vx: (Math.random() - 0.5) * 4,
      vy: (Math.random() - 0.5) * 4,
      radius: Math.random() * 3 + 1,
      alpha: 1
    });
  }
}

function draw() {
  // Clear canvas
  ctx.fillStyle = '#0d131f';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Grid background subtle pattern
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
  ctx.lineWidth = 1;
  for (let i = 0; i < GRID_SIZE; i++) {
    ctx.beginPath();
    ctx.moveTo(i * CELL_SIZE, 0);
    ctx.lineTo(i * CELL_SIZE, canvas.height);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(0, i * CELL_SIZE);
    ctx.lineTo(canvas.width, i * CELL_SIZE);
    ctx.stroke();
  }

  // Draw food (apple)
  ctx.fillStyle = '#ff4757';
  ctx.beginPath();
  ctx.arc(food.x * CELL_SIZE + CELL_SIZE / 2, food.y * CELL_SIZE + CELL_SIZE / 2, CELL_SIZE / 2 - 2, 0, Math.PI * 2);
  ctx.fill();

  // Food glow
  ctx.shadowColor = '#ff4757';
  ctx.shadowBlur = 8;
  ctx.fill();
  ctx.shadowBlur = 0;

  // Draw snake
  snake.forEach((seg, i) => {
    const isHead = i === 0;
    ctx.fillStyle = isHead ? '#00f2fe' : '#4facfe';
    const padding = 1;
    ctx.fillRect(
      seg.x * CELL_SIZE + padding,
      seg.y * CELL_SIZE + padding,
      CELL_SIZE - padding * 2,
      CELL_SIZE - padding * 2
    );

    // Eyes on head
    if (isHead) {
      ctx.fillStyle = '#000';
      const eyeOffset = 4;
      const eyeSize = 3;
      ctx.fillRect(seg.x * CELL_SIZE + eyeOffset, seg.y * CELL_SIZE + eyeOffset, eyeSize, eyeSize);
      ctx.fillRect(seg.x * CELL_SIZE + CELL_SIZE - eyeOffset - eyeSize, seg.y * CELL_SIZE + eyeOffset, eyeSize, eyeSize);
    }
  });

  // Draw particles
  particles.forEach((p, idx) => {
    p.x += p.vx;
    p.y += p.vy;
    p.alpha -= 0.05;
    if (p.alpha <= 0) {
      particles.splice(idx, 1);
    } else {
      ctx.fillStyle = `rgba(0, 242, 254, ${p.alpha})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
      ctx.fill();
    }
  });
}

function triggerGameOver() {
  isGameOver = true;
  if (gameLoopInterval) clearInterval(gameLoopInterval);
  window.gameBridge.reportGameOver(score, 'lost', () => resetGame());
}

function updateScoreUI() {
  document.getElementById('score-display').textContent = score;
  document.getElementById('high-score-display').textContent = highScore;
}

function setDirection(x, y) {
  // Prevent 180-degree immediate turn
  if (direction.x + x === 0 && direction.y + y === 0) return;
  nextDirection = { x, y };
}

function setupControls() {
  // Keyboard
  window.addEventListener('keydown', (e) => {
    switch (e.key) {
      case 'ArrowUp': case 'w': case 'W': setDirection(0, -1); break;
      case 'ArrowDown': case 's': case 'S': setDirection(0, 1); break;
      case 'ArrowLeft': case 'a': case 'A': setDirection(-1, 0); break;
      case 'ArrowRight': case 'd': case 'D': setDirection(1, 0); break;
    }
  });

  // Touch D-Pad buttons
  document.getElementById('btn-up').addEventListener('click', () => setDirection(0, -1));
  document.getElementById('btn-down').addEventListener('click', () => setDirection(0, 1));
  document.getElementById('btn-left').addEventListener('click', () => setDirection(-1, 0));
  document.getElementById('btn-right').addEventListener('click', () => setDirection(1, 0));

  // Touch Swipe on canvas
  let touchStartX = 0;
  let touchStartY = 0;

  canvas.addEventListener('touchstart', (e) => {
    const t = e.touches[0];
    touchStartX = t.clientX;
    touchStartY = t.clientY;
  }, { passive: true });

  canvas.addEventListener('touchend', (e) => {
    const t = e.changedTouches[0];
    const dx = t.clientX - touchStartX;
    const dy = t.clientY - touchStartY;

    if (Math.abs(dx) > Math.abs(dy)) {
      if (dx > 20) setDirection(1, 0);
      else if (dx < -20) setDirection(-1, 0);
    } else {
      if (dy > 20) setDirection(0, 1);
      else if (dy < -20) setDirection(0, -1);
    }
  }, { passive: true });
}

document.addEventListener('DOMContentLoaded', init);
