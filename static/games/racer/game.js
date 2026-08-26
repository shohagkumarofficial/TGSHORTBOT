/**
 * Speed Racer Arcade Game Logic
 */
const canvas = document.getElementById('racer-canvas');
const ctx = canvas.getContext('2d');
const startHint = document.getElementById('start-hint');

const LANES = [80, 160, 240]; // 3 lane centers
let currentLaneIndex = 1; // 0: Left, 1: Center, 2: Right

let gameState = 'ready'; // 'ready', 'playing', 'over'
let distance = 0;
let highScore = 0;
let speed = 5; // road speed
let roadOffset = 0;

let playerCar = {
  x: LANES[1],
  y: 380,
  targetX: LANES[1],
  width: 38,
  height: 60
};

let traffic = [];
let particles = [];
let spawnTimer = 0;
let animFrameId = null;

function init() {
  window.gameBridge.init('racer');
  setupControls();
  resetGame();
  gameLoop();
}

function resetGame() {
  currentLaneIndex = 1;
  playerCar.x = LANES[1];
  playerCar.targetX = LANES[1];
  traffic = [];
  particles = [];
  distance = 0;
  speed = 5;
  spawnTimer = 0;
  gameState = 'ready';
  updateScoreUI();
  if (startHint) startHint.style.display = 'block';
}

function steer(dir) {
  if (gameState === 'ready') {
    gameState = 'playing';
    if (startHint) startHint.style.display = 'none';
  }

  if (gameState !== 'playing') return;

  if (dir === 'left' && currentLaneIndex > 0) {
    currentLaneIndex--;
    window.soundManager?.playClick();
    window.tgApp?.hapticImpact('light');
  } else if (dir === 'right' && currentLaneIndex < 2) {
    currentLaneIndex++;
    window.soundManager?.playClick();
    window.tgApp?.hapticImpact('light');
  }

  playerCar.targetX = LANES[currentLaneIndex];
}

function spawnTrafficCar() {
  const lane = Math.floor(Math.random() * 3);
  const colors = ['#e74c3c', '#f1c40f', '#9b59b6', '#1abc9c'];
  const color = colors[Math.floor(Math.random() * colors.length)];

  // Prevent spawning if lane already crowded near top
  if (traffic.some(t => t.lane === lane && t.y < 120)) return;

  traffic.push({
    lane: lane,
    x: LANES[lane],
    y: -70,
    width: 38,
    height: 58,
    speed: Math.random() * 1.5 + 2.5,
    color: color
  });
}

function update() {
  // Road scrolling
  roadOffset = (roadOffset + speed) % 40;

  if (gameState !== 'playing') return;

  distance += Math.floor(speed / 2);
  speed = Math.min(14, 5 + Math.floor(distance / 500) * 0.8);
  if (distance > highScore) highScore = distance;
  updateScoreUI();

  // Smooth car steering
  playerCar.x += (playerCar.targetX - playerCar.x) * 0.28;

  // Spawn traffic
  spawnTimer++;
  if (spawnTimer % Math.max(35, 75 - Math.floor(speed * 2)) === 0) {
    spawnTrafficCar();
  }

  // Update traffic
  for (let i = traffic.length - 1; i >= 0; i--) {
    const t = traffic[i];
    t.y += speed - t.speed;

    // Collision detection
    if (
      Math.abs(playerCar.x - t.x) < (playerCar.width + t.width) / 2 - 6 &&
      Math.abs(playerCar.y - t.y) < (playerCar.height + t.height) / 2 - 8
    ) {
      createCrashParticles(playerCar.x, playerCar.y);
      triggerGameOver();
      return;
    }

    // Passed bottom
    if (t.y > canvas.height + 80) {
      traffic.splice(i, 1);
      window.soundManager?.playScore();
    }
  }

  // Update particles
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.x += p.vx;
    p.y += p.vy;
    p.alpha -= 0.03;
    if (p.alpha <= 0) particles.splice(i, 1);
  }
}

function createCrashParticles(x, y) {
  for (let i = 0; i < 20; i++) {
    particles.push({
      x, y,
      vx: (Math.random() - 0.5) * 8,
      vy: (Math.random() - 0.5) * 8,
      radius: Math.random() * 4 + 1,
      color: Math.random() > 0.5 ? '#ff4757' : '#ffd200',
      alpha: 1
    });
  }
}

function drawCar(x, y, color, isPlayer = false) {
  ctx.save();
  ctx.translate(x, y);

  // Wheels
  ctx.fillStyle = '#000';
  ctx.fillRect(-22, -22, 6, 12);
  ctx.fillRect(16, -22, 6, 12);
  ctx.fillRect(-22, 12, 6, 12);
  ctx.fillRect(16, 12, 6, 12);

  // Body
  ctx.fillStyle = color;
  if (isPlayer) {
    ctx.shadowColor = color;
    ctx.shadowBlur = 10;
  }
  ctx.beginPath();
  ctx.roundRect(-16, -28, 32, 56, 6);
  ctx.fill();
  ctx.shadowBlur = 0;

  // Windshield
  ctx.fillStyle = isPlayer ? '#00f2fe' : '#2c3e50';
  ctx.fillRect(-12, -14, 24, 10);
  ctx.fillRect(-10, 6, 20, 8);

  // Headlights
  ctx.fillStyle = isPlayer ? '#ffd700' : '#e74c3c';
  const lightY = isPlayer ? -26 : 24;
  ctx.fillRect(-12, lightY, 6, 3);
  ctx.fillRect(6, lightY, 6, 3);

  ctx.restore();
}

function draw() {
  // Road background
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Grass borders
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(0, 0, 30, canvas.height);
  ctx.fillRect(canvas.width - 30, 0, 30, canvas.height);

  // Curb stripes
  ctx.fillStyle = '#ff4757';
  for (let y = -40 + roadOffset; y < canvas.height; y += 40) {
    ctx.fillRect(26, y, 4, 20);
    ctx.fillRect(canvas.width - 30, y, 4, 20);
  }

  // Lane dividers (dashed lines)
  ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
  for (let y = -40 + roadOffset; y < canvas.height; y += 40) {
    ctx.fillRect(120 - 2, y, 4, 20);
    ctx.fillRect(200 - 2, y, 4, 20);
  }

  // Traffic cars
  traffic.forEach(t => {
    drawCar(t.x, t.y, t.color, false);
  });

  // Player car
  if (gameState !== 'over') {
    drawCar(playerCar.x, playerCar.y, '#00f2fe', true);
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
  window.soundManager?.playExplosion();
  window.gameBridge.reportGameOver(distance, 'lost', () => resetGame());
}

function updateScoreUI() {
  document.getElementById('score-display').textContent = `${distance}m`;
  document.getElementById('speed-display').textContent = `${Math.floor(speed * 20)} km/h`;
  document.getElementById('high-score-display').textContent = `${highScore}m`;
}

function setupControls() {
  document.getElementById('btn-left').addEventListener('click', () => steer('left'));
  document.getElementById('btn-right').addEventListener('click', () => steer('right'));

  // Touch canvas left/right half
  canvas.addEventListener('pointerdown', (e) => {
    const rect = canvas.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    if (clickX < rect.width / 2) {
      steer('left');
    } else {
      steer('right');
    }
  });

  window.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft' || e.key === 'a') steer('left');
    if (e.key === 'ArrowRight' || e.key === 'd') steer('right');
  });
}

document.addEventListener('DOMContentLoaded', init);
