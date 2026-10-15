/**
 * J.A.R.V.I.S. Holographic Interface & Arc Reactor Engine
 * Stark Industries - Protocol v4.2
 */

class JarvisHUD {
  constructor() {
    this.ws = null;
    this.state = 'STANDBY'; // STANDBY, LISTENING, PROCESSING, SPEAKING
    this.audioLevel = 0;
    this.autostartEnabled = false;
    
    // 3D Holographic Golden Matrix Engine
    this.canvas = document.getElementById('arcCanvas');
    this.ctx = this.canvas.getContext('2d');
    this.yaw = 0;
    this.pitch = 0.35;
    this.roll = 0.12;
    this.speedFactor = 1.0;
    this.initSphereParticles();
    
    // Equalizer
    this.eqContainer = document.getElementById('eq-bars');
    this.numEqBars = 28;
    this.initEqBars();
    
    // Audio Context for UI Sound Effects
    this.audioCtx = null;
    
    // Speech Recognition in Browser (Web Speech API)
    this.recognition = null;
    this.isBrowserListening = false;
    this.continuousMode = false;
    
    // DOM Elements
    this.statusBadge = document.getElementById('status-badge');
    this.statusText = document.getElementById('status-text');
    this.coreState = document.getElementById('core-state');
    this.micBtn = document.getElementById('mic-trigger-btn');
    this.continuousCb = document.getElementById('continuous-mic-cb');
    this.autostartBtn = document.getElementById('autostart-btn');
    this.autostartDot = document.getElementById('autostart-dot');
    this.autostartLabel = document.getElementById('autostart-label');
    this.cmdInput = document.getElementById('cmd-input');
    this.cmdForm = document.getElementById('command-form');
    this.terminalFeed = document.getElementById('terminal-feed');
    this.clearLogBtn = document.getElementById('clear-log-btn');
    this.stopBtn = document.getElementById('stop-jarvis-btn');
    
    // Telemetry Elements
    this.cpuGauge = document.getElementById('cpu-gauge');
    this.cpuVal = document.getElementById('cpu-val');
    this.cpuSub = document.getElementById('cpu-sub');
    this.ramGauge = document.getElementById('ram-gauge');
    this.ramVal = document.getElementById('ram-val');
    this.ramSub = document.getElementById('ram-sub');
    this.diskGauge = document.getElementById('disk-gauge');
    this.diskVal = document.getElementById('disk-val');
    this.diskSub = document.getElementById('disk-sub');
    this.uptimeVal = document.getElementById('uptime-val');
    this.hostVal = document.getElementById('host-val');

    this.initClock();
    this.initEvents();
    this.initWebSpeech();
    this.connectWebSocket();
    this.startAnimationLoop();
  }

  /* ---------------- CLOCK ---------------- */
  initClock() {
    const updateTime = () => {
      const now = new Date();
      document.getElementById('hud-clock').textContent = now.toTimeString().split(' ')[0];
      const months = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ'];
      document.getElementById('hud-date').textContent = `${String(now.getDate()).padStart(2, '0')} ${months[now.getMonth()]} ${now.getFullYear()}`;
    };
    updateTime();
    setInterval(updateTime, 1000);
  }

  /* ---------------- SOUND FX ---------------- */
  playBeep(freq = 900, duration = 0.1) {
    try {
      if (!this.audioCtx) {
        this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (this.audioCtx.state === 'suspended') {
        this.audioCtx.resume();
      }
      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, this.audioCtx.currentTime);
      gain.gain.setValueAtTime(0.08, this.audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, this.audioCtx.currentTime + duration);
      osc.connect(gain);
      gain.connect(this.audioCtx.destination);
      osc.start();
      osc.stop(this.audioCtx.currentTime + duration);
    } catch (e) {
      // Audio autoplay policy
    }
  }

  /* ---------------- EQUALIZER ---------------- */
  initEqBars() {
    this.eqContainer.innerHTML = '';
    for (let i = 0; i < this.numEqBars; i++) {
      const bar = document.createElement('div');
      bar.className = 'eq-bar';
      this.eqContainer.appendChild(bar);
    }
  }

  updateEqBars() {
    const bars = this.eqContainer.children;
    for (let i = 0; i < bars.length; i++) {
      let targetHeight = 4;
      if (this.state === 'SPEAKING' || this.state === 'LISTENING') {
        const factor = Math.sin((Date.now() / 150) + i * 0.4) * 0.5 + 0.5;
        targetHeight = Math.max(4, Math.floor((this.audioLevel * 30 + factor * 26)));
      } else {
        targetHeight = 4 + Math.sin((Date.now() / 400) + i * 0.2) * 2;
      }
      bars[i].style.height = `${targetHeight}px`;
    }
  }

  /* ---------------- WEBSOCKET ---------------- */
  connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log('[JARVIS] Conectado ao servidor principal.');
      this.setState('STANDBY');
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch (e) {
        console.error('Erro ao processar mensagem WS:', e);
      }
    };

    this.ws.onclose = () => {
      console.log('[JARVIS] Desconectado. Reconectando em 2 segundos...');
      this.setState('DESCONECTADO');
      setTimeout(() => this.connectWebSocket(), 2000);
    };

    this.ws.onerror = (err) => {
      console.error('[JARVIS] Erro WS:', err);
    };
  }

  handleMessage(msg) {
    switch (msg.type) {
      case 'init':
        this.updateTelemetry(msg.telemetry);
        break;
      case 'telemetry':
        this.updateTelemetry(msg.data);
        break;
      case 'state':
        this.setState(msg.state);
        break;
      case 'audio_level':
        this.audioLevel = msg.level;
        break;
      case 'user_command':
        this.addFeedEntry('SENHOR', msg.text, true);
        break;
      case 'jarvis_response':
        this.addFeedEntry('J.A.R.V.I.S.', msg.response, false, msg.thought);
        break;
      case 'autostart_status':
        this.setAutostartStatus(msg.enabled);
        break;
    }
  }

  sendCommand(text) {
    if (!text || !text.trim()) return;
    this.playBeep(1200, 0.08);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        action: 'command',
        command: text.trim()
      }));
    }
  }

  /* ---------------- BROWSER SPEECH RECOGNITION ---------------- */
  initWebSpeech() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      this.recognition = new SpeechRecognition();
      this.recognition.lang = 'pt-BR';
      this.recognition.continuous = true;
      this.recognition.interimResults = false;

      this.recognition.onstart = () => {
        this.isBrowserListening = true;
        this.micBtn.classList.add('active');
        this.setState('LISTENING');
      };

      this.recognition.onresult = (event) => {
        const lastIdx = event.results.length - 1;
        const transcript = event.results[lastIdx][0].transcript.trim();
        console.log('[Voz Reconhecida]:', transcript);
        if (transcript) {
          this.sendCommand(transcript);
        }
      };

      this.recognition.onerror = (event) => {
        console.warn('Erro SpeechRecognition:', event.error);
        if (event.error !== 'no-speech' && !this.continuousMode) {
          this.stopBrowserListening();
        }
      };

      this.recognition.onend = () => {
        this.isBrowserListening = false;
        if (this.continuousMode) {
          // Restart listening in continuous mode
          try { this.recognition.start(); } catch (e) {}
        } else {
          this.micBtn.classList.remove('active');
          this.setState('STANDBY');
        }
      };
    }
  }

  toggleBrowserListening() {
    if (!this.recognition) {
      // Fallback: trigger backend sounddevice listening
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'listen_trigger' }));
      }
      return;
    }

    if (this.isBrowserListening) {
      this.stopBrowserListening();
    } else {
      this.startBrowserListening();
    }
  }

  startBrowserListening() {
    this.playBeep(1000, 0.12);
    try {
      this.recognition.start();
    } catch (e) {
      console.warn('Recognition start err:', e);
    }
  }

  stopBrowserListening() {
    this.playBeep(700, 0.08);
    try {
      this.recognition.stop();
    } catch (e) {}
    this.isBrowserListening = false;
    this.micBtn.classList.remove('active');
    this.setState('STANDBY');
  }

  /* ---------------- UI STATE ---------------- */
  setState(newState) {
    this.state = newState.toUpperCase();
    this.coreState.textContent = this.state;
    this.statusBadge.className = 'status-indicator';

    switch (this.state) {
      case 'LISTENING':
      case 'ESCUTANDO':
        this.statusBadge.classList.add('listening');
        this.statusText.textContent = 'ESCUTANDO VOZ...';
        this.speedFactor = 2.4;
        break;
      case 'PROCESSING':
      case 'PROCESSANDO':
        this.statusBadge.classList.add('processing');
        this.statusText.textContent = 'PROCESSANDO DADOS...';
        this.speedFactor = 4.5;
        break;
      case 'SPEAKING':
      case 'FALANDO':
        this.statusText.textContent = 'TRANSMITINDO VOZ...';
        this.speedFactor = 2.0;
        break;
      case 'STANDBY':
      case 'PRONTO':
      default:
        this.statusText.textContent = 'SISTEMAS OPERACIONAIS';
        this.speedFactor = 1.0;
        break;
    }
  }

  updateTelemetry(data) {
    if (!data) return;

    // CPU Gauge
    const cpu = Math.round(data.cpu_percent || 0);
    this.cpuVal.textContent = `${cpu}%`;
    this.updateGaugeRing(this.cpuGauge, cpu);
    this.cpuSub.textContent = `${data.cpu_cores || 4} Cores // ${data.cpu_ghz || 0} GHz`;

    // RAM Gauge
    const ram = Math.round(data.ram_percent || 0);
    this.ramVal.textContent = `${ram}%`;
    this.updateGaugeRing(this.ramGauge, ram);
    this.ramSub.textContent = `${data.ram_used_gb || 0} GB / ${data.ram_total_gb || 0} GB`;

    // Disk Gauge
    const disk = Math.round(data.disk_percent || 0);
    this.diskVal.textContent = `${disk}%`;
    this.updateGaugeRing(this.diskGauge, disk);
    this.diskSub.textContent = `${data.disk_free_gb || 0} GB Livres`;

    // Details
    if (data.uptime) this.uptimeVal.textContent = data.uptime;
    if (data.hostname) this.hostVal.textContent = data.hostname;

    if (data.autostart_enabled !== undefined) {
      this.setAutostartStatus(data.autostart_enabled);
    }
  }

  updateGaugeRing(element, percent) {
    if (!element) return;
    const circumference = 2 * Math.PI * 40; // 251.2
    const offset = circumference - (percent / 100) * circumference;
    element.style.strokeDashoffset = offset;
  }

  setAutostartStatus(enabled) {
    this.autostartEnabled = enabled;
    if (enabled) {
      this.autostartDot.classList.add('active');
      this.autostartLabel.textContent = 'BOOT: ATIVO';
      this.autostartBtn.title = 'Inicialização automática ativa. Clique para desativar.';
    } else {
      this.autostartDot.classList.remove('active');
      this.autostartLabel.textContent = 'BOOT: DESATIVADO';
      this.autostartBtn.title = 'Inicialização automática desativada. Clique para ativar.';
    }
  }

  addFeedEntry(sender, text, isUser = false, thought = null) {
    const entry = document.createElement('div');
    entry.className = `feed-entry ${isUser ? 'user-msg' : 'jarvis-msg'}`;

    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

    let thoughtHtml = '';
    if (thought) {
      thoughtHtml = `
        <div class="feed-thought">
          <span class="thought-badge">◈ HERMES COGNITION</span>
          <div class="thought-body">${this.escapeHtml(thought)}</div>
        </div>
      `;
    }

    entry.innerHTML = `
      <div class="entry-header">
        <span class="entry-sender">${sender}</span>
        <span class="entry-time">${timeStr}</span>
      </div>
      ${thoughtHtml}
      <div class="entry-content">${this.escapeHtml(text)}</div>
    `;

    this.terminalFeed.appendChild(entry);
    this.terminalFeed.scrollTop = this.terminalFeed.scrollHeight;
  }

  escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* ---------------- EVENTS ---------------- */
  initEvents() {
    // Form submit
    this.cmdForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const val = this.cmdInput.value;
      if (val) {
        this.sendCommand(val);
        this.cmdInput.value = '';
      }
    });

    // Mic button
    this.micBtn.addEventListener('click', () => {
      this.toggleBrowserListening();
    });

    // Continuous listening checkbox
    this.continuousCb.addEventListener('change', (e) => {
      this.continuousMode = e.target.checked;
      if (this.continuousMode) {
        this.startBrowserListening();
      } else {
        this.stopBrowserListening();
      }
    });

    // Autostart toggle
    this.autostartBtn.addEventListener('click', () => {
      this.playBeep(1100, 0.08);
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'toggle_autostart' }));
      }
    });

    // Stop / Shutdown button
    if (this.stopBtn) {
      this.stopBtn.addEventListener('click', () => {
        if (confirm('Deseja realmente encerrar todos os processos do JARVIS?')) {
          this.shutdownJarvis();
        }
      });
    }

    // Auto-shutdown backend when window is closed
    window.addEventListener('beforeunload', () => {
      try {
        navigator.sendBeacon('/api/shutdown');
      } catch (e) {
        fetch('/api/shutdown', { method: 'POST', keepalive: true }).catch(() => {});
      }
    });

    // Clear feed
    this.clearLogBtn.addEventListener('click', () => {
      this.terminalFeed.innerHTML = '';
    });

    // Quick Macro buttons
    document.querySelectorAll('.macro-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const cmd = btn.getAttribute('data-cmd');
        if (cmd) {
          this.sendCommand(cmd);
        }
      });
    });
  }

  shutdownJarvis() {
    this.playBeep(400, 0.2);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'shutdown' }));
    }
    try {
      navigator.sendBeacon('/api/shutdown');
    } catch (e) {
      fetch('/api/shutdown', { method: 'POST', keepalive: true }).catch(() => {});
    }
    setTimeout(() => {
      window.close();
    }, 350);
  }

  /* ---------------- 3D HOLOGRAPHIC GOLDEN SPHERE ENGINE ---------------- */
  initSphereParticles() {
    this.particles = [];
    const count = 160;
    for (let i = 0; i < count; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const rRatio = Math.pow(Math.random(), 0.65);
      const r = 75 + rRatio * 165;
      this.particles.push({
        baseR: r,
        theta: theta,
        phi: phi,
        size: Math.random() * 2.2 + 0.8,
        speed: (Math.random() * 0.012 + 0.004) * (Math.random() > 0.5 ? 1 : -1),
        flicker: Math.random() * Math.PI * 2
      });
    }
  }

  startAnimationLoop() {
    const render = () => {
      this.drawGoldenHolographicSphere();
      this.updateEqBars();
      requestAnimationFrame(render);
    };
    requestAnimationFrame(render);
  }

  drawGoldenHolographicSphere() {
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const cx = w / 2;
    const cy = h / 2;

    ctx.clearRect(0, 0, w, h);

    // Continuous 3D rotation
    this.yaw += 0.009 * this.speedFactor;
    this.roll += 0.003 * this.speedFactor;
    const audioAmp = (this.audioLevel * 45) + (this.state === 'SPEAKING' ? 16 : (this.state === 'LISTENING' ? 8 : 2));

    // 3D rotation matrix
    const cosY = Math.cos(this.yaw), sinY = Math.sin(this.yaw);
    const cosP = Math.cos(this.pitch), sinP = Math.sin(this.pitch);
    const cosR = Math.cos(this.roll), sinR = Math.sin(this.roll);

    const project = (x, y, z) => {
      // Rotate Y (yaw)
      let x1 = x * cosY + z * sinY;
      let y1 = y;
      let z1 = -x * sinY + z * cosY;

      // Rotate X (pitch)
      let x2 = x1;
      let y2 = y1 * cosP - z1 * sinP;
      let z2 = y1 * sinP + z1 * cosP;

      // Rotate Z (roll)
      let x3 = x2 * cosR - y2 * sinR;
      let y3 = x2 * sinR + y2 * cosR;
      let z3 = z2;

      const fov = 440;
      const zDist = z3 + 370;
      if (zDist < 10) return null;
      const scale = fov / zDist;
      return {
        x: cx + x3 * scale,
        y: cy + y3 * scale,
        scale: scale,
        z: z3
      };
    };

    // Helper: Draw 3D Orbit Ring
    const drawOrbitRing = (radius, tiltX, tiltY, tiltZ, rotSpeed, segments, strokeStyle, lineWidth, isDashed = false, hasNotches = false) => {
      const ringAngle = this.yaw * rotSpeed;
      const cosTX = Math.cos(tiltX), sinTX = Math.sin(tiltX);
      const cosTY = Math.cos(tiltY), sinTY = Math.sin(tiltY);
      const cosTZ = Math.cos(tiltZ), sinTZ = Math.sin(tiltZ);

      const transformRingPoint = (rad, angle) => {
        let rx = rad * Math.cos(angle);
        let ry = rad * Math.sin(angle);
        let rz = 0;

        // Apply ring tilt
        let y1 = ry * cosTX - rz * sinTX;
        let z1 = ry * sinTX + rz * cosTX;

        let x2 = rx * cosTY + z1 * sinTY;
        let y2 = y1;
        let z2 = -rx * sinTY + z1 * cosTY;

        let x3 = x2 * cosTZ - y2 * sinTZ;
        let y3 = x2 * sinTZ + y2 * cosTZ;
        let z3 = z2;

        return project(x3, y3, z3);
      };

      ctx.save();
      ctx.lineWidth = lineWidth;
      if (isDashed) ctx.setLineDash([8, 12]);

      // Draw segments
      ctx.beginPath();
      let first = true;
      for (let s = 0; s <= segments; s++) {
        const phi = (s / segments) * Math.PI * 2 + ringAngle;
        let r = radius;
        // Audio modulation on outer ring
        if (hasNotches && s % 3 === 0) {
          r += Math.sin(s * 4 + Date.now() / 120) * (audioAmp * 0.15);
        }
        const p = transformRingPoint(r, phi);
        if (!p) continue;
        if (first) {
          ctx.moveTo(p.x, p.y);
          first = false;
        } else {
          ctx.lineTo(p.x, p.y);
        }
      }
      ctx.strokeStyle = strokeStyle;
      ctx.shadowBlur = 10;
      ctx.shadowColor = '#ffb700';
      ctx.stroke();

      // Draw Notches / Markers if enabled
      if (hasNotches) {
        ctx.setLineDash([]);
        for (let k = 0; k < 36; k++) {
          const kAngle = (k / 36) * Math.PI * 2 + ringAngle;
          const p1 = transformRingPoint(radius - 6, kAngle);
          const p2 = transformRingPoint(radius + 8, kAngle);
          if (p1 && p2) {
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.strokeStyle = k % 4 === 0 ? '#ffe680' : 'rgba(255, 183, 0, 0.45)';
            ctx.lineWidth = k % 4 === 0 ? 2 : 1;
            ctx.stroke();
          }
        }
      }
      ctx.restore();
    };

    // 1. Draw 3D Orbital Rings (Matching MCU Golden Spherical Core)
    // Equator Ring with audio reactive notches
    drawOrbitRing(238, 0.12, 0.0, 0.05, 0.35, 64, 'rgba(255, 183, 0, 0.7)', 1.5, false, true);

    // Primary Tilted Orbit 1 (45° tilt)
    drawOrbitRing(220, Math.PI / 4, Math.PI / 6, 0.2, -0.6, 64, 'rgba(255, 140, 0, 0.75)', 2.0, true, false);

    // Primary Tilted Orbit 2 (-35° tilt)
    drawOrbitRing(198, -Math.PI / 5, Math.PI / 3, -0.3, 0.8, 64, 'rgba(255, 200, 50, 0.8)', 1.8, false, false);

    // Polar Meridian Orbit (80° tilt)
    drawOrbitRing(182, Math.PI / 2.3, -0.2, Math.PI / 4, -0.5, 48, 'rgba(255, 110, 0, 0.65)', 1.5, true, false);

    // Inner Gyro Orbit (55° tilt)
    drawOrbitRing(148, Math.PI / 3, -Math.PI / 4, 0.5, 1.2, 48, 'rgba(255, 220, 80, 0.85)', 2.2, false, false);

    // Fast Core Orbit
    drawOrbitRing(105, -Math.PI / 3, Math.PI / 5, -0.4, -1.6, 36, 'rgba(255, 170, 0, 0.9)', 2.0, false, false);

    // 2. Swirling Golden Spiral Filaments (Energy whirlpool around core)
    ctx.save();
    for (let arm = 0; arm < 3; arm++) {
      ctx.beginPath();
      const armOffset = (arm * Math.PI * 2 / 3) + this.yaw * 1.5;
      let firstArm = true;
      for (let step = 0; step < 40; step++) {
        const spiralT = step / 40;
        const rad = 30 + spiralT * 125;
        const ang = armOffset + spiralT * 3.5;
        const sx = rad * Math.cos(ang);
        const sy = rad * Math.sin(ang) * 0.7; // Tilted spiral plane
        const sz = (1 - spiralT) * 40 * Math.sin(spiralT * Math.PI);
        const p = project(sx, sy, sz);
        if (!p) continue;
        if (firstArm) {
          ctx.moveTo(p.x, p.y);
          firstArm = false;
        } else {
          ctx.lineTo(p.x, p.y);
        }
      }
      ctx.strokeStyle = 'rgba(255, 215, 0, 0.65)';
      ctx.lineWidth = 1.5;
      ctx.shadowBlur = 12;
      ctx.shadowColor = '#ffaa00';
      ctx.stroke();
    }
    ctx.restore();

    // 3. 3D Particle Cloud (Golden data sparks & neural nodes)
    ctx.save();
    for (let pt of this.particles) {
      pt.theta += pt.speed * this.speedFactor;
      pt.flicker += 0.08;

      let px3d = pt.baseR * Math.sin(pt.phi) * Math.cos(pt.theta);
      let py3d = pt.baseR * Math.sin(pt.phi) * Math.sin(pt.theta);
      let pz3d = pt.baseR * Math.cos(pt.phi);

      const prj = project(px3d, py3d, pz3d);
      if (!prj) continue;

      // Depth based alpha: points in front (pz > 0) are brighter
      const depthAlpha = Math.max(0.15, Math.min(1.0, (prj.z + 200) / 400));
      const flickerAlpha = (Math.sin(pt.flicker) * 0.3 + 0.7) * depthAlpha;

      ctx.fillStyle = prj.z > 0 ? `rgba(255, 240, 180, ${flickerAlpha})` : `rgba(255, 140, 0, ${flickerAlpha * 0.7})`;
      ctx.shadowBlur = prj.z > 0 ? 8 : 3;
      ctx.shadowColor = '#ffb700';

      ctx.beginPath();
      ctx.arc(prj.x, prj.y, pt.size * prj.scale, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();

    // 4. Central Singularity / Radiant Golden Core
    const coreRadius = 22 + (audioAmp * 0.45);
    const grad = ctx.createRadialGradient(cx, cy, 2, cx, cy, coreRadius * 2.8);
    grad.addColorStop(0, '#ffffff');
    grad.addColorStop(0.25, '#ffe57f');
    grad.addColorStop(0.55, 'rgba(255, 150, 0, 0.85)');
    grad.addColorStop(0.85, 'rgba(255, 70, 0, 0.35)');
    grad.addColorStop(1, 'transparent');

    ctx.save();
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, coreRadius * 2.8, 0, Math.PI * 2);
    ctx.fill();

    // Core white flare
    ctx.fillStyle = '#ffffff';
    ctx.shadowBlur = 20;
    ctx.shadowColor = '#ffe066';
    ctx.beginPath();
    ctx.arc(cx, cy, 8 + (audioAmp * 0.15), 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}

// Instantiate on load
window.addEventListener('DOMContentLoaded', () => {
  window.jarvis = new JarvisHUD();
});
