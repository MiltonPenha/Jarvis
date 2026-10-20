class ReactorVisuals {
  initSphereParticles() {
    this.particles = [];
    const count = 96;
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
    let last=0;
    const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const render = (timestamp) => {
      if(!document.hidden&&(last===0||timestamp-last>=(reduced?1000:['LISTENING','PROCESSING','EXECUTING'].includes(this.state)?50:100))){
        this.drawGoldenHolographicSphere();
        this.updateEqBars();
        last=timestamp;
      }
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
    const audioAmp = (this.audioLevel * 45) + (this.speechPhase === 'playing' ? 16 : (this.state === 'LISTENING' ? 8 : 2));

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
