/**
 * Neon Breakout Arcade Game Logic
 */
const canvas = document.getElementById('breakout-canvas');
const ctx = canvas.getContext('2d');
const startHint = document.getElementById('start-hint');

let gameState = 'ready'; // 'ready', 'playing', 'over'
let score = 0;
let highScore = 0;
let remainingBricks = 0;

let paddle = {
  x: 160,
  y: 420,
  width: 76,
  height: 12,
  targetX: 160
};

let ball = {
  x: 160,
  y: 405,
  radius: 6,
  vx: 3,
  vy: -5,
  speed: 5.5
};

const BRICK_ROWS = 5;
const BRICK_COLS = 6;
const BRICK_WIDTH = 46;
const BRICK_HEIGHT = 16;
const BRICK_PADDING = 6;
const BRICK_OFFSET_TOP = 40;
const BRICK_OFFSET_LEFT = 8;

const ROW_COLORS = ['#ff007f', '#7928ca', '#00f2fe', '#ffd700', '#2ed573'];

let bricks = [];
let particles = [];
let animFrameId = null;

function init() {
  window.gameBridge.init('breakout');
  setupControls();
  resetGame();
  gameLoop();
}

function initBricks() {
  bricks = [];
  remainingBricks = 0;
  for (let r = 0; r < BRICK_ROWS; r++) {
    bricks[r] = [];
    for (let c = 0; c < BRICK_COLS; c++) {
      bricks[r][c] = {
        x: BRICK_OFFSET_LEFT + c * (BRICK_WIDTH + BRICK_PADDING),
        y: BRICK_OFFSET_TOP + r * (BRICK_HEIGHT + BRICK_PADDING),
        status: 1,
        color: ROW_COLORS[r % ROW_COLORS.length]
      };
      remainingBricks++;
    }
  }
}

function resetGame() {
  paddle.x = 160;
  paddle.targetX = 160;
  ball.x = 160;
  ball.y = 405;
  ball.vx = (Math.random() - 0.5) * 4;
  ball.vy = -5.5;
  score = 0;
  particles = [];
  gameState = 'ready';
  initBricks();
  updateScoreUI();
  if (startHint) startHint.style.display = 'block';
}

function update() {
  if (gameState !== 'playing') return;

  // Smooth paddle follow
  paddle.x += (paddle.targetX - paddle.x) * 0.35;
  paddle.x = Math.max(paddle.width / 2, Math.min(canvas.width - paddle.width / 2, paddle.x));

  // Move ball
  ball.x += ball.vx;
  ball.y += ball.vy;

  // Wall collisions (Left/Right)
  if (ball.x - ball.radius <= 0) {
    ball.x = ball.radius;
    ball.vx = -ball.vx;
    window.soundManager?.playClick();
  } else if (ball.x + ball.radius >= canvas.width) {
    ball.x = canvas.width - ball.radius;
    ball.vx = -ball.vx;
    window.soundManager?.playClick();
  }

  // Ceiling collision
  if (ball.y - ball.radius <= 0) {
    ball.y = ball.radius;
    ball.vy = -ball.vy;
    window.soundManager?.playClick();
  }

  // Paddle collision
  if (
    ball.y + ball.radius >= paddle.y - paddle.height / 2 &&
    ball.y - ball.radius <= paddle.y + paddle.height / 2 &&
    ball.x >= paddle.x - paddle.width / 2 &&
    ball.x <= paddle.x + paddle.width / 2
  ) {
    ball.vy = -Math.abs(ball.vy);
    // Angle deflection based on hit position
    const hitOffset = (ball.x - paddle.x) / (paddle.width / 2);
    ball.vx = hitOffset * 5.5;
    window.soundManager?.playFlap();
    window.tgApp?.hapticImpact('light');
  }

  // Brick collisions
  for (let r = 0; r < BRICK_ROWS; r++) {
    for (let c = 0; c < BRICK_COLS; c++) {
      const b = bricks[r][c];
      if (b.status === 1) {
        if (
          ball.x + ball.radius > b.x &&
          ball.x - ball.radius < b.x + BRICK_WIDTH &&
          ball.y + ball.radius > b.y &&
          ball.y - ball.radius < b.y + BRICK_HEIGHT
        ) {
          ball.vy = -ball.vy;
          b.status = 0;
          remainingBricks--;
          score += 25;
          if (score > highScore) highScore = score;
          updateScoreUI();
          createBrickParticles(b.x + BRICK_WIDTH / 2, b.y + BRICK_HEIGHT / 2, b.color);
          window.soundManager?.playHit();
          window.tgApp?.hapticImpact('medium');

          if (remainingBricks <= 0) {
            handleVictory();
            return;
          }
        }
      }
    }
  }

  // Bottom edge (Missed ball -> Game Over)
  if (ball.y - ball.radius > canvas.height) {
    triggerGameOver();
    return;
  }

  // Update particles
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.x += p.vx;
    p.y += p.vy;
    p.alpha -= 0.04;
    if (p.alpha <= 0) particles.splice(i, 1);
  }
}

function createBrickParticles(x, y, color) {
  for (let i = 0; i < 10; i++) {
    particles.push({
      x, y,
      vx: (Math.random() - 0.5) * 5,
      vy: (Math.random() - 0.5) * 5,
      radius: Math.random() * 3 + 1,
      color: color,
      alpha: 1
    });
  }
}

function draw() {
  // Clear canvas
  ctx.fillStyle = '#090e1a';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Draw bricks
  for (let r = 0; r < BRICK_ROWS; r++) {
    for (let c = 0; c < BRICK_COLS; c++) {
      const b = bricks[r][c];
      if (b.status === 1) {
        ctx.fillStyle = b.color;
        ctx.shadowColor = b.color;
        ctx.shadowBlur = 6;
        ctx.beginPath();
        ctx.roundRect(b.x, b.y, BRICK_WIDTH, BRICK_HEIGHT, 4);
        ctx.fill();
        ctx.shadowBlur = 0;
      }
    }
  }

  // Draw paddle
  ctx.fillStyle = '#00f2fe';
  ctx.shadowColor = '#00f2fe';
  ctx.shadowBlur = 10;
  ctx.beginPath();
  ctx.roundRect(paddle.x - paddle.width / 2, paddle.y - paddle.height / 2, paddle.width, paddle.height, 6);
  ctx.fill();
  ctx.shadowBlur = 0;

  // Draw ball
  ctx.fillStyle = '#fff';
  ctx.shadowColor = '#ffd700';
  ctx.shadowBlur = 10;
  ctx.beginPath();
  ctx.arc(ball.x, ball.y, ball.radius, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;

  // Draw particles
  particles.forEach(p => {
    ctx.fillStyle = p.color;
    ctx.globalAlpha = p.alpha;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  });
}

function gameLoop() {
  update();
  draw();
  animFrameId = requestAnimationFrame(gameLoop);
}

function handleVictory() {
  gameState = 'over';
  window.gameBridge.reportGameOver(score, 'won', () => resetGame());
}

function triggerGameOver() {
  gameState = 'over';
  window.gameBridge.reportGameOver(score, 'lost', () => resetGame());
}

function updateScoreUI() {
  document.getElementById('score-display').textContent = score;
  document.getElementById('bricks-display').textContent = remainingBricks;
  document.getElementById('high-score-display').textContent = highScore;
}

function setupControls() {
  function handleInput(clientX) {
    const rect = canvas.getBoundingClientRect();
    paddle.targetX = (clientX - rect.left) * (canvas.width / rect.width);

    if (gameState === 'ready') {
      gameState = 'playing';
      if (startHint) startHint.style.display = 'none';
    }
  }

  canvas.addEventListener('pointerdown', (e) => {
    handleInput(e.clientX);
  });

  canvas.addEventListener('pointermove', (e) => {
    if (e.buttons > 0 || e.pointerType === 'touch') {
      handleInput(e.clientX);
    }
  });

  window.addEventListener('keydown', (e) => {
    if (gameState === 'ready') {
      gameState = 'playing';
      if (startHint) startHint.style.display = 'none';
    }
    const step = 25;
    if (e.key === 'ArrowLeft' || e.key === 'a') paddle.targetX -= step;
    if (e.key === 'ArrowRight' || e.key === 'd') paddle.targetX += step;
  });
}

document.addEventListener('DOMContentLoaded', init);
