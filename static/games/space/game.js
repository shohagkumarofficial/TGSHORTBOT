/**
 * Space Shooter Arcade Game Logic
 */
const canvas = document.getElementById('space-canvas');
const ctx = canvas.getContext('2d');
const startHint = document.getElementById('start-hint');

let gameState = 'ready'; // 'ready', 'playing', 'over'
let score = 0;
let highScore = 0;
let wave = 1;

let player = {
  x: 160,
  y: 400,
  width: 32,
  height: 36,
  speed: 6,
  targetX: 160,
  targetY: 400
};

let bullets = [];
let enemies = [];
let particles = [];
let stars = [];
let shootTimer = 0;
let spawnTimer = 0;
let animFrameId = null;

function init() {
  window.gameBridge.init('space');
  initStars();
  setupControls();
  resetGame();
  gameLoop();
}

function initStars() {
  stars = [];
  for (let i = 0; i < 45; i++) {
    stars.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      size: Math.random() * 2 + 0.5,
      speed: Math.random() * 1.5 + 0.5
    });
  }
}

function resetGame() {
  player.x = 160;
  player.y = 400;
  player.targetX = 160;
  player.targetY = 400;
  bullets = [];
  enemies = [];
  particles = [];
  score = 0;
  wave = 1;
  shootTimer = 0;
  spawnTimer = 0;
  gameState = 'ready';
  updateScoreUI();
  if (startHint) startHint.style.display = 'block';
}

function spawnEnemy() {
  const size = Math.random() * 12 + 20;
  enemies.push({
    x: Math.random() * (canvas.width - size),
    y: -size,
    size: size,
    hp: size > 28 ? 2 : 1,
    speed: Math.random() * 1.5 + 1.2 + (wave * 0.2),
    color: size > 28 ? '#ff007f' : '#00f2fe'
  });
}

function update() {
  // Update stars
  stars.forEach(s => {
    s.y += s.speed;
    if (s.y > canvas.height) {
      s.y = 0;
      s.x = Math.random() * canvas.width;
    }
  });

  if (gameState !== 'playing') return;

  // Smooth player movement
  player.x += (player.targetX - player.x) * 0.25;
  player.y += (player.targetY - player.y) * 0.25;
  player.x = Math.max(player.width / 2, Math.min(canvas.width - player.width / 2, player.x));
  player.y = Math.max(player.height / 2, Math.min(canvas.height - player.height / 2, player.y));

  // Auto fire
  shootTimer++;
  if (shootTimer % 12 === 0) {
    bullets.push({
      x: player.x,
      y: player.y - player.height / 2,
      vy: -9
    });
    window.soundManager?.playLaser();
  }

  // Update bullets
  for (let i = bullets.length - 1; i >= 0; i--) {
    const b = bullets[i];
    b.y += b.vy;
    if (b.y < -10) bullets.splice(i, 1);
  }

  // Spawn enemies
  spawnTimer++;
  if (spawnTimer % Math.max(25, 60 - wave * 4) === 0) {
    spawnEnemy();
  }

  // Update enemies
  for (let i = enemies.length - 1; i >= 0; i--) {
    const e = enemies[i];
    e.y += e.speed;

    // Bullet-Enemy Collisions
    for (let j = bullets.length - 1; j >= 0; j--) {
      const b = bullets[j];
      if (
        b.x > e.x && b.x < e.x + e.size &&
        b.y > e.y && b.y < e.y + e.size
      ) {
        bullets.splice(j, 1);
        e.hp--;
        if (e.hp <= 0) {
          createExplosion(e.x + e.size / 2, e.y + e.size / 2, e.color);
          enemies.splice(i, 1);
          score += 20;
          if (score % 200 === 0) wave++;
          if (score > highScore) highScore = score;
          updateScoreUI();
          window.soundManager?.playExplosion();
          window.tgApp?.hapticImpact('light');
        }
        break;
      }
    }

    // Player-Enemy Collision
    if (
      player.x + player.width / 2 > e.x &&
      player.x - player.width / 2 < e.x + e.size &&
      player.y + player.height / 2 > e.y &&
      player.y - player.height / 2 < e.y + e.size
    ) {
      createExplosion(player.x, player.y, '#00f2fe');
      triggerGameOver();
      return;
    }

    // Enemy passed bottom
    if (e.y > canvas.height + 20) {
      enemies.splice(i, 1);
    }
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

function createExplosion(x, y, color) {
  for (let i = 0; i < 14; i++) {
    particles.push({
      x, y,
      vx: (Math.random() - 0.5) * 6,
      vy: (Math.random() - 0.5) * 6,
      radius: Math.random() * 3 + 1,
      color: color,
      alpha: 1
    });
  }
}

function draw() {
  // Background
  ctx.fillStyle = '#060913';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Stars
  ctx.fillStyle = '#ffffff';
  stars.forEach(s => {
    ctx.fillRect(s.x, s.y, s.size, s.size);
  });

  // Bullets
  ctx.fillStyle = '#00f2fe';
  ctx.shadowColor = '#00f2fe';
  ctx.shadowBlur = 8;
  bullets.forEach(b => {
    ctx.fillRect(b.x - 2, b.y, 4, 12);
  });
  ctx.shadowBlur = 0;

  // Enemies
  enemies.forEach(e => {
    ctx.fillStyle = e.color;
    ctx.shadowColor = e.color;
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.moveTo(e.x + e.size / 2, e.y + e.size);
    ctx.lineTo(e.x, e.y);
    ctx.lineTo(e.x + e.size, e.y);
    ctx.closePath();
    ctx.fill();
    ctx.shadowBlur = 0;
  });

  // Player Ship
  if (gameState !== 'over') {
    ctx.save();
    ctx.translate(player.x, player.y);

    // Thruster flame
    ctx.fillStyle = '#ff4757';
    ctx.beginPath();
    ctx.moveTo(-6, player.height / 2);
    ctx.lineTo(0, player.height / 2 + Math.random() * 12 + 6);
    ctx.lineTo(6, player.height / 2);
    ctx.closePath();
    ctx.fill();

    // Ship Body
    ctx.fillStyle = '#00f2fe';
    ctx.shadowColor = '#4facfe';
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.moveTo(0, -player.height / 2);
    ctx.lineTo(-player.width / 2, player.height / 2);
    ctx.lineTo(0, player.height / 2 - 6);
    ctx.lineTo(player.width / 2, player.height / 2);
    ctx.closePath();
    ctx.fill();
    ctx.shadowBlur = 0;

    // Cockpit
    ctx.fillStyle = '#fff';
    ctx.fillRect(-2, -6, 4, 10);
    ctx.restore();
  }

  // Particles
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

function triggerGameOver() {
  gameState = 'over';
  window.gameBridge.reportGameOver(score, 'lost', () => resetGame());
}

function updateScoreUI() {
  document.getElementById('score-display').textContent = score;
  document.getElementById('wave-display').textContent = wave;
  document.getElementById('high-score-display').textContent = highScore;
}

function setupControls() {
  function handleInput(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    player.targetX = (clientX - rect.left) * (canvas.width / rect.width);
    player.targetY = (clientY - rect.top) * (canvas.height / rect.height);

    if (gameState === 'ready') {
      gameState = 'playing';
      if (startHint) startHint.style.display = 'none';
    }
  }

  canvas.addEventListener('pointerdown', (e) => {
    handleInput(e.clientX, e.clientY);
  });

  canvas.addEventListener('pointermove', (e) => {
    if (e.buttons > 0 || e.pointerType === 'touch') {
      handleInput(e.clientX, e.clientY);
    }
  });

  window.addEventListener('keydown', (e) => {
    if (gameState === 'ready') {
      gameState = 'playing';
      if (startHint) startHint.style.display = 'none';
    }
    const step = 20;
    if (e.key === 'ArrowLeft' || e.key === 'a') player.targetX -= step;
    if (e.key === 'ArrowRight' || e.key === 'd') player.targetX += step;
    if (e.key === 'ArrowUp' || e.key === 'w') player.targetY -= step;
    if (e.key === 'ArrowDown' || e.key === 's') player.targetY += step;
  });
}

document.addEventListener('DOMContentLoaded', init);
