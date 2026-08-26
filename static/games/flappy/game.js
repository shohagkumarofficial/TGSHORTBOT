/**
 * Flappy Bird Game Logic
 */
const canvas = document.getElementById('flappy-canvas');
const ctx = canvas.getContext('2d');
const startHint = document.getElementById('start-hint');

let gameState = 'ready'; // 'ready', 'playing', 'over'
let score = 0;
let highScore = 0;

let bird = {
  x: 60,
  y: 200,
  vy: 0,
  radius: 12,
  gravity: 0.38,
  jump: -6.8
};

let pipes = [];
let pipeSpawnTimer = 0;
const PIPE_GAP = 120;
const PIPE_WIDTH = 52;
const PIPE_SPEED = 2.2;
let animFrameId = null;

function init() {
  window.gameBridge.init('flappy');
  setupControls();
  resetGame();
  gameLoop();
}

function resetGame() {
  bird.y = 200;
  bird.vy = 0;
  pipes = [];
  pipeSpawnTimer = 0;
  score = 0;
  gameState = 'ready';
  if (startHint) startHint.style.display = 'block';
}

function flap() {
  if (gameState === 'ready') {
    gameState = 'playing';
    if (startHint) startHint.style.display = 'none';
  }

  if (gameState === 'playing') {
    bird.vy = bird.jump;
    window.tgApp?.hapticImpact('light');
  }
}

function spawnPipe() {
  const minHeight = 50;
  const maxHeight = canvas.height - PIPE_GAP - minHeight - 40;
  const topHeight = Math.floor(Math.random() * (maxHeight - minHeight + 1)) + minHeight;

  pipes.push({
    x: canvas.width,
    topHeight: topHeight,
    bottomY: topHeight + PIPE_GAP,
    passed: false
  });
}

function update() {
  if (gameState !== 'playing') return;

  // Update bird
  bird.vy += bird.gravity;
  bird.y += bird.vy;

  // Ground collision
  if (bird.y + bird.radius >= canvas.height - 30) {
    triggerGameOver();
    return;
  }
  // Ceiling collision
  if (bird.y - bird.radius <= 0) {
    bird.y = bird.radius;
    bird.vy = 0;
  }

  // Update & spawn pipes
  pipeSpawnTimer++;
  if (pipeSpawnTimer % 90 === 0) {
    spawnPipe();
  }

  for (let i = pipes.length - 1; i >= 0; i--) {
    const p = pipes[i];
    p.x -= PIPE_SPEED;

    // Check score
    if (!p.passed && p.x + PIPE_WIDTH < bird.x) {
      p.passed = true;
      score++;
      if (score > highScore) highScore = score;
      window.tgApp?.hapticImpact('light');
    }

    // Check collision
    // Top pipe
    if (
      bird.x + bird.radius > p.x &&
      bird.x - bird.radius < p.x + PIPE_WIDTH &&
      bird.y - bird.radius < p.topHeight
    ) {
      triggerGameOver();
      return;
    }

    // Bottom pipe
    if (
      bird.x + bird.radius > p.x &&
      bird.x - bird.radius < p.x + PIPE_WIDTH &&
      bird.y + bird.radius > p.bottomY
    ) {
      triggerGameOver();
      return;
    }

    // Remove off-screen pipes
    if (p.x + PIPE_WIDTH < -10) {
      pipes.splice(i, 1);
    }
  }
}

function draw() {
  // Background
  const grad = ctx.createLinearGradient(0, 0, 0, canvas.height);
  grad.addColorStop(0, '#0a1128');
  grad.addColorStop(1, '#1c2541');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Background stars / grid
  ctx.fillStyle = 'rgba(255, 255, 255, 0.2)';
  for (let i = 1; i <= 8; i++) {
    ctx.fillRect((i * 45) % canvas.width, (i * 65) % 300, 2, 2);
  }

  // Draw pipes
  pipes.forEach(p => {
    ctx.fillStyle = '#00c6ff';
    ctx.shadowColor = '#0072ff';
    ctx.shadowBlur = 10;

    // Top pipe
    ctx.fillRect(p.x, 0, PIPE_WIDTH, p.topHeight);
    ctx.fillRect(p.x - 3, p.topHeight - 16, PIPE_WIDTH + 6, 16);

    // Bottom pipe
    const bottomHeight = canvas.height - p.bottomY;
    ctx.fillRect(p.x, p.bottomY, PIPE_WIDTH, bottomHeight);
    ctx.fillRect(p.x - 3, p.bottomY, PIPE_WIDTH + 6, 16);

    ctx.shadowBlur = 0;
  });

  // Draw ground
  ctx.fillStyle = '#0b132b';
  ctx.fillRect(0, canvas.height - 30, canvas.width, 30);
  ctx.fillStyle = '#4facfe';
  ctx.fillRect(0, canvas.height - 30, canvas.width, 3);

  // Draw bird
  ctx.save();
  ctx.translate(bird.x, bird.y);
  let rotation = Math.min(Math.PI / 4, Math.max(-Math.PI / 4, (bird.vy * 4) * Math.PI / 180));
  ctx.rotate(rotation);

  // Body
  ctx.fillStyle = '#ffd200';
  ctx.beginPath();
  ctx.arc(0, 0, bird.radius, 0, Math.PI * 2);
  ctx.fill();

  // Wing
  ctx.fillStyle = '#f7971e';
  ctx.beginPath();
  ctx.arc(-3, 2, 6, 0, Math.PI * 2);
  ctx.fill();

  // Eye
  ctx.fillStyle = '#fff';
  ctx.beginPath();
  ctx.arc(4, -4, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#000';
  ctx.beginPath();
  ctx.arc(5, -4, 2, 0, Math.PI * 2);
  ctx.fill();

  // Beak
  ctx.fillStyle = '#ff4757';
  ctx.beginPath();
  ctx.moveTo(8, -1);
  ctx.lineTo(15, 2);
  ctx.lineTo(8, 5);
  ctx.closePath();
  ctx.fill();

  ctx.restore();

  // Score HUD
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 26px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(score, canvas.width / 2, 50);
}

function gameLoop() {
  update();
  draw();
  animFrameId = requestAnimationFrame(gameLoop);
}

function triggerGameOver() {
  gameState = 'over';
  window.gameBridge.reportGameOver(score, 'lost', () => resetGame());
}

function setupControls() {
  canvas.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    flap();
  });

  window.addEventListener('keydown', (e) => {
    if (e.code === 'Space' || e.key === 'ArrowUp') {
      e.preventDefault();
      flap();
    }
  });
}

document.addEventListener('DOMContentLoaded', init);
