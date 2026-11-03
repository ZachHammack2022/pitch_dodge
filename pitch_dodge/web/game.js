/*
 * Pitch Dodge, browser edition.
 *
 * The Python server analyses songs and builds charts; this file plays them:
 * audio, drawing, input and screens. The rules live in rules.js.
 * Song time comes from the Web Audio clock, so notes stay locked to the music
 * even if frames drop, and pausing suspends both together.
 */
(function () {
  'use strict';

  const {
    WIDTH, HEIGHT, TOP_MARGIN, DIFFICULTY_ORDER, PADDLE_WIDTH, PADDLE_X, MAX_FRAME, clamp, pitchToY, Song, World,
  } = window.PitchDodgeRules; // rules.js

  // ------------------------------------------------------------ audio

  class Audio {
    constructor() {
      this.ctx = null;
      this.buffer = null;
      this.source = null;
      this.startedAt = 0;
      this.muted = false;
      this.offset = 0; // extra delay the player measured (seconds), e.g. for Bluetooth headphones
    }

    ensure() {
      if (!this.ctx) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        this.ctx = new Ctx();
        this.master = this.ctx.createGain();
        this.master.connect(this.ctx.destination);
        this.musicGain = this.ctx.createGain();
        this.musicGain.connect(this.master);
        this.master.gain.value = this.muted ? 0 : 1;
      }
      return this.ctx;
    }

    async load(arrayBuffer) {
      const ctx = this.ensure();
      this.buffer = await new Promise((resolve, reject) => ctx.decodeAudioData(arrayBuffer, resolve, reject));
    }

    /** Start the song ``countIn`` seconds from now; position() is negative until then. */
    async play(countIn = 0) {
      const ctx = this.ensure();
      this.stop();
      if (ctx.state === 'suspended') await ctx.resume();
      this.source = ctx.createBufferSource();
      this.source.buffer = this.buffer;
      this.source.connect(this.musicGain);
      this.startedAt = ctx.currentTime + Math.max(0.05, countIn);
      this.source.start(this.startedAt);
    }

    stop() {
      this.holdStop();
      if (this.source) {
        try { this.source.stop(); } catch (e) { /* already stopped */ }
        this.source.disconnect();
        this.source = null;
      }
    }

    /** A soft sustained tone in key while the player holds a hold note. */
    holdStart(midi, seconds) {
      if (!this.ctx || this.muted) return;
      this.holdStop();
      const now = this.ctx.currentTime;
      const hz = 440 * 2 ** ((midi - 69) / 12);
      const g = this.ctx.createGain();
      g.gain.setValueAtTime(0.0001, now);
      g.gain.exponentialRampToValueAtTime(0.05, now + 0.03);
      g.gain.exponentialRampToValueAtTime(0.025, now + seconds);
      g.connect(this.master);
      const oscs = [hz, hz * 2].map((f, i) => {
        const o = this.ctx.createOscillator();
        o.type = i ? 'sine' : 'triangle';
        o.frequency.value = f;
        o.connect(g);
        o.start(now);
        o.stop(now + seconds + 0.3);
        return o;
      });
      this.holdVoice = { g, oscs };
    }

    holdStop() {
      const v = this.holdVoice;
      if (!v || !this.ctx) return;
      this.holdVoice = null;
      const now = this.ctx.currentTime;
      v.g.gain.cancelScheduledValues(now);
      v.g.gain.setValueAtTime(Math.max(v.g.gain.value, 0.0001), now);
      v.g.gain.exponentialRampToValueAtTime(0.0001, now + 0.12);
      for (const o of v.oscs) { try { o.stop(now + 0.15); } catch (e) { /* already stopped */ } }
    }

    pause() { if (this.ctx) return this.ctx.suspend(); }
    resume() { if (this.ctx) return this.ctx.resume(); }

    /** Seconds into the song, as heard (compensating for output latency). */
    position() {
      if (!this.ctx || !this.source) return 0;
      const latency = this.ctx.outputLatency || this.ctx.baseLatency || 0;
      return this.ctx.currentTime - this.startedAt - latency - this.offset;
    }

    /** A metronome click at context time ``when`` (for calibration). */
    click(when, accent) {
      const osc = this.ctx.createOscillator();
      const g = this.ctx.createGain();
      osc.frequency.value = accent ? 1760 : 1320;
      g.gain.setValueAtTime(0.0001, when);
      g.gain.exponentialRampToValueAtTime(0.5, when + 0.002);
      g.gain.exponentialRampToValueAtTime(0.0001, when + 0.06);
      osc.connect(g).connect(this.master);
      osc.start(when);
      osc.stop(when + 0.08);
    }

    setMuted(m) {
      this.muted = m;
      if (this.master) this.master.gain.value = m ? 0 : 1;
    }

    /**
     * Small synthesised effects. Success sounds take the song's current pitch
     * class (``midi``) so playing well adds notes in key instead of clashing.
     */
    sfx(kind, midi = 72, value = 0) {
      if (!this.ctx || this.muted) return;
      const hz = (m) => 440 * 2 ** ((m - 69) / 12);
      const presets = {
        hit:       { freqs: [110, 82], dur: 0.35, vol: 0.35, type: 'sawtooth' },
        catch:     { freqs: [hz(midi), hz(midi + 12)], dur: 0.3, vol: 0.08, type: 'triangle' },
        perfect:   { freqs: [hz(midi), hz(midi + 12), hz(midi + 19)], dur: 0.35, vol: 0.09, type: 'triangle' },
        miss:      { freqs: [hz(midi - 24)], dur: 0.12, vol: 0.03, type: 'sine' },
        level_up:  { freqs: [hz(midi), hz(midi + 7), hz(midi + 12)], dur: 0.35, vol: 0.08, type: 'triangle', arp: 0.06 },
        game_over: { freqs: [196, 147, 98], dur: 0.9, vol: 0.2, type: 'triangle', arp: 0.18 },
        cleared:   { freqs: [523, 659, 784, 1047], dur: 0.9, vol: 0.12, type: 'triangle', arp: 0.1 },
      };
      if (kind === 'hold_start') return this.holdStart(midi, value / 1000);
      if (kind === 'hold_break') return this.holdStop();
      if (kind === 'hold_done') { this.holdStop(); kind = 'level_up'; }
      const p = presets[kind];
      if (!p) return;
      const now = this.ctx.currentTime;
      p.freqs.forEach((f, i) => {
        const t0 = now + (p.arp || 0) * i;
        const osc = this.ctx.createOscillator();
        const g = this.ctx.createGain();
        osc.type = p.type;
        osc.frequency.value = f;
        g.gain.setValueAtTime(0.0001, t0);
        g.gain.exponentialRampToValueAtTime(p.vol, t0 + 0.005);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + p.dur);
        osc.connect(g).connect(this.master);
        osc.start(t0);
        osc.stop(t0 + p.dur + 0.05);
      });
    }
  }

  // ------------------------------------------------------------ drawing

  const COLORS = {
    text: '#ebebf5', dim: '#8c87aa', accent: '#78ffaa', danger: '#ff5064', gold: '#ffd25a',
  };

  function pitchColor(pitch) {
    const hue = (0.02 + 0.7 * clamp(pitch, 0, 1)) * 360;
    return `hsl(${hue.toFixed(0)}, 100%, 62%)`;
  }

  class Renderer {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.particles = [];
      this.popups = [];
      this.shake = 0;
      this.flash = 0;
      this.glowCache = new Map();
      this.resize();
    }

    resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const stage = document.getElementById('stage');
      const scale = Math.min(window.innerWidth / WIDTH, window.innerHeight / HEIGHT) * 0.98;
      stage.style.transform = `translate(-50%, -50%) scale(${scale})`;
      const px = dpr * Math.max(1, scale);
      this.canvas.width = Math.round(WIDTH * px);
      this.canvas.height = Math.round(HEIGHT * px);
      this.ctx.setTransform(px, 0, 0, px, 0, 0);
      this.pixelRatio = px;
    }

    glow(color, radius) {
      const key = color + radius;
      let c = this.glowCache.get(key);
      if (!c) {
        const size = radius * 6;
        c = document.createElement('canvas');
        c.width = c.height = Math.ceil(size * 2);
        const g = c.getContext('2d');
        g.scale(2, 2);
        const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
        grad.addColorStop(0, color);
        grad.addColorStop(0.3, color);
        grad.addColorStop(0.36, color.replace('hsl', 'hsla').replace(')', ', 0.35)'));
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        g.fillStyle = grad;
        g.fillRect(0, 0, size, size);
        g.fillStyle = 'rgba(255,255,255,0.85)';
        g.beginPath();
        g.arc(size / 2, size / 2, Math.max(2, radius / 2), 0, Math.PI * 2);
        g.fill();
        c.size = size;
        this.glowCache.set(key, c);
      }
      return c;
    }

    blitGlow(color, radius, x, y) {
      const c = this.glow(color, Math.round(radius));
      this.ctx.drawImage(c, x - c.size / 2, y - c.size / 2, c.size, c.size);
    }

    burst(x, y, color, n, speed, life = 0.6, size = 3) {
      for (let i = 0; i < n; i++) {
        const a = Math.random() * Math.PI * 2;
        const s = (0.3 + Math.random() * 0.7) * speed;
        this.particles.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, life, maxLife: life, color, size });
      }
    }

    react(events) {
      for (const e of events) {
        if (e.kind === 'hit') {
          this.burst(e.x, e.y, COLORS.danger, 40, 420, 0.8, 4);
          this.shake = 0.35;
          this.flash = 0.25;
          this.popups.push({ text: 'OUCH', x: e.x - 110, y: e.y - 20, life: 0.8, color: COLORS.danger });
        } else if (e.kind === 'perfect') {
          this.burst(e.x, e.y, COLORS.gold, 18, 240);
          this.judge(`PERFECT +${e.value}`, e.x - 170, e.y - 26, COLORS.gold);
        } else if (e.kind === 'catch') {
          this.burst(e.x, e.y, COLORS.accent, 10, 180, 0.5, 3);
        } else if (e.kind === 'miss') {
          this.burst(e.x, e.y, COLORS.dim, 6, 80, 0.4, 2);
          this.judge('miss', e.x - 70, e.y - 20, COLORS.dim);
        } else if (e.kind === 'hold_done') {
          this.burst(e.x, e.y, COLORS.gold, 14, 200);
          this.judge(`HELD +${e.value}`, e.x - 150, e.y - 26, COLORS.gold);
        } else if (e.kind === 'hold_break') {
          this.judge('slipped', e.x - 100, e.y - 20, COLORS.dim);
        } else if (e.kind === 'level_up') {
          this.popups.push({ text: `x${e.value}!`, x: WIDTH / 2 - 30, y: HEIGHT / 2 - 40, life: 1.0, color: COLORS.accent });
        } else if (e.kind === 'spawn') {
          this.burst(6, e.y, COLORS.text, 4, 90, 0.3, 2);
        }
      }
    }

    /** Catch/miss labels replace each other instead of piling up. */
    judge(text, x, y, color) {
      this.popups = this.popups.filter((p) => !p.judge);
      this.popups.push({ text, x, y, life: 0.45, color, judge: true });
    }

    tick(dt) {
      for (const p of this.particles) {
        p.x += p.vx * dt; p.y += p.vy * dt;
        p.vx *= 0.92; p.vy = p.vy * 0.92 + 300 * dt;
        p.life -= dt;
      }
      this.particles = this.particles.filter((p) => p.life > 0);
      for (const p of this.popups) { p.y -= 40 * dt; p.life -= dt; }
      this.popups = this.popups.filter((p) => p.life > 0);
      this.shake = Math.max(0, this.shake - dt);
      this.flash = Math.max(0, this.flash - dt);
    }

    clearEffects() { this.particles = []; this.popups = []; this.shake = this.flash = 0; }

    /** How hard the beat is hitting right now: 1 on a beat, decaying to 0; downbeats (every 4th) hit harder. */
    beatPulse(beats, t) {
      let lo = 0, hi = beats.length - 1, i = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (beats[mid] <= t) { i = mid; lo = mid + 1; } else hi = mid - 1;
      }
      if (i < 0) return 0;
      const strength = i % 4 === 0 ? 1 : 0.6;
      return strength * Math.exp(-(t - beats[i]) * 8);
    }

    /** A hold note's tail: a bar back from the head along the time it's held for. */
    holdTail(w, n, color) {
      const c = this.ctx;
      const xEnd = n.x - n.duration * w.speed;
      const xStart = n.holding ? Math.min(n.x, w.paddle.x + w.paddle.width / 2) : n.x;
      if (xStart <= xEnd) return;
      const live = n.holding && !n.holdBroken;
      const dead = n.passed && !n.hit; // head was missed
      const h = n.radius * (live ? 1.3 : 0.9);
      c.globalAlpha = dead ? 0.25 : live ? 0.9 : 0.5;
      c.fillStyle = dead ? COLORS.dim : color;
      roundRect(c, xEnd, n.y - h / 2, xStart - xEnd, h, h / 2);
      c.globalAlpha = 1;
    }

    hazard(x, y, r, t) {
      const c = this.ctx;
      this.blitGlow('hsl(352, 100%, 66%)', Math.round(r * 0.6), x, y);
      c.fillStyle = COLORS.danger;
      c.beginPath();
      for (let i = 0; i < 16; i++) {
        const a = t * 3 + (i * Math.PI * 2) / 16;
        const rr = r * (i % 2 === 0 ? 1 : 0.5);
        const px = x + Math.cos(a) * rr, py = y + Math.sin(a) * rr;
        i ? c.lineTo(px, py) : c.moveTo(px, py);
      }
      c.closePath();
      c.fill();
      c.fillStyle = '#280812';
      c.beginPath();
      c.arc(x, y, Math.max(2, r * 0.32), 0, Math.PI * 2);
      c.fill();
    }

    background() {
      const g = this.ctx.createLinearGradient(0, 0, 0, HEIGHT);
      g.addColorStop(0, '#0a0818');
      g.addColorStop(1, '#180a28');
      this.ctx.fillStyle = g;
      this.ctx.fillRect(-20, -20, WIDTH + 40, HEIGHT + 40);
    }

    titleScene(t) {
      const c = this.ctx;
      this.background();
      const wave = (x) => HEIGHT * 0.9 + Math.sin(x / 70 + t * 2) * 30 + Math.sin(x / 23 + t * 3) * 8;
      c.strokeStyle = '#5a46a0';
      c.lineWidth = 3;
      c.beginPath();
      for (let x = 0; x <= WIDTH; x += 8) (x ? c.lineTo(x, wave(x)) : c.moveTo(x, wave(x)));
      c.stroke();
      for (let i = 0; i < 7; i++) {
        const x = ((t * 220 + i * 150) % (WIDTH + 100)) - 50;
        this.blitGlow(pitchColor(i / 6), 9, x, HEIGHT * 0.9 + Math.sin(x / 70 + t * 2) * 30);
      }
    }

    worldScene(w) {
      const c = this.ctx;
      const t = w.songTime;
      c.save();
      if (this.shake > 0) {
        const mag = 10 * this.shake / 0.35;
        c.translate((Math.random() * 2 - 1) * mag, (Math.random() * 2 - 1) * mag);
      }
      this.background();

      // Grid pulsing with loudness and the beat.
      const energy = w.song.energyAt(t);
      const pulse = t >= 0 ? this.beatPulse(w.chart.beats, t) : 0;
      c.strokeStyle = `rgba(120, 90, 220, ${(10 + 30 * energy + 40 * pulse) / 255})`;
      c.lineWidth = 1;
      c.beginPath();
      for (let x = 0; x < WIDTH; x += 48) { c.moveTo(x + 0.5, TOP_MARGIN); c.lineTo(x + 0.5, HEIGHT); }
      for (let y = TOP_MARGIN; y < HEIGHT; y += 48) { c.moveTo(0, y + 0.5); c.lineTo(WIDTH, y + 0.5); }
      c.stroke();

      // Upcoming beats as lines scrolling toward the paddle (every 4th brighter).
      const beats = w.chart.beats;
      for (let i = 0; i < beats.length; i++) {
        const x = PADDLE_X - (beats[i] - t) * w.speed;
        if (x < 0) break;
        if (x > PADDLE_X + 4) continue;
        c.fillStyle = i % 4 === 0 ? 'rgba(160, 140, 255, 0.16)' : 'rgba(160, 140, 255, 0.07)';
        c.fillRect(x - 1, TOP_MARGIN, 2, HEIGHT - TOP_MARGIN);
      }

      // The melody path: a line through the upcoming catch notes, where they will be.
      c.save();
      c.beginPath();
      c.rect(0, TOP_MARGIN, PADDLE_X + PADDLE_WIDTH / 2, HEIGHT - TOP_MARGIN);
      c.clip(); // nothing past the paddle
      c.strokeStyle = '#5a46a0';
      c.lineWidth = 2;
      c.beginPath();
      let started = false;
      for (const n of w.chart.notes) {
        if (n.kind !== 'catch') continue;
        const x = w.xAt(n.t, t);
        const xEnd = w.xAt(n.t + (n.duration || 0), t); // the paddle stays put through a hold
        if (xEnd > PADDLE_X + 40) continue;
        const y = pitchToY(n.pitch);
        started ? c.lineTo(x, y) : c.moveTo(x, y);
        if (n.duration) c.lineTo(xEnd, y);
        started = true;
        if (x < -40) break;
      }
      c.stroke();
      c.restore();
      const ahead = t + w.chart.travel_time;
      if (ahead >= 0 && ahead <= w.duration) {
        const pitch = w.song.pitchAt(ahead);
        this.blitGlow(pitchColor(pitch), 7 + Math.round(5 * energy + 4 * pulse), 4, pitchToY(pitch));
      }

      // Notes with trails; hazards are spinning red spikes.
      for (const n of w.notes) {
        if (n.kind === 'hazard') { this.hazard(n.x, n.y, n.radius * 1.4, t); continue; }
        const color = pitchColor(n.pitch);
        if (n.duration > 0) this.holdTail(w, n, color);
        if (n.hit) continue; // head already caught; only the tail is left
        for (let i = 3; i >= 1; i--) {
          c.globalAlpha = 0.5 - i * 0.12;
          c.fillStyle = color;
          c.beginPath();
          c.arc(n.x - i * n.radius * 0.9, n.y, Math.max(2, n.radius - i * 2), 0, Math.PI * 2);
          c.fill();
        }
        c.globalAlpha = 1;
        this.blitGlow(color, n.radius, n.x, n.y);
      }

      // Paddle, blinking while invulnerable.
      const p = w.paddle;
      if (!w.invulnerable || Math.floor(t * 12) % 2 === 0) {
        const top = p.y - p.height / 2;
        const grow = 12 + 6 * pulse;
        c.fillStyle = `rgba(120, 255, 170, ${0.18 + 0.3 * pulse})`;
        roundRect(c, p.x - grow, top - grow, p.width + 2 * grow, p.height + 2 * grow, 14);
        c.fillStyle = COLORS.accent;
        roundRect(c, p.x, top, p.width, p.height, 6);
        c.fillStyle = '#dcffe6';
        roundRect(c, p.x + 4, top + 4, p.width - 8, p.height - 8, 4);
      }

      for (const pt of this.particles) {
        c.globalAlpha = pt.life / pt.maxLife;
        c.fillStyle = pt.color;
        c.beginPath();
        c.arc(pt.x, pt.y, Math.max(1, pt.size * c.globalAlpha), 0, Math.PI * 2);
        c.fill();
      }
      c.globalAlpha = 1;
      c.font = '600 20px -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif';
      c.textBaseline = 'top';
      for (const pu of this.popups) {
        c.globalAlpha = Math.min(1, pu.life * 2);
        c.fillStyle = pu.color;
        c.fillText(pu.text, pu.x, pu.y);
      }
      c.globalAlpha = 1;
      c.restore();

      if (t < 0) {  // count-in
        c.font = '800 96px -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif';
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        c.fillStyle = 'rgba(235, 235, 245, 0.55)';
        c.fillText(String(Math.floor(-t) + 1), WIDTH / 2, HEIGHT / 2);
        c.textAlign = 'left';
      }

      if (this.flash > 0) {
        c.fillStyle = `rgba(255, 40, 60, ${0.47 * this.flash / 0.25})`;
        c.fillRect(0, 0, WIDTH, HEIGHT);
      }
    }

    hud(w, best, muted) {
      const c = this.ctx;
      c.fillStyle = 'rgba(0,0,0,0.47)';
      c.fillRect(0, 0, WIDTH, TOP_MARGIN);
      c.strokeStyle = '#3c3264';
      c.beginPath(); c.moveTo(0, TOP_MARGIN + 0.5); c.lineTo(WIDTH, TOP_MARGIN + 0.5); c.stroke();

      c.textBaseline = 'middle';
      const font = (size, weight = 600) => `${weight} ${size}px -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif`;
      c.font = font(30, 800);
      c.fillStyle = COLORS.text;
      c.fillText(w.score.toLocaleString(), 16, 26);
      c.font = font(20, 700);
      c.fillStyle = w.multiplier > 1 ? COLORS.accent : COLORS.dim;
      c.fillText(`x${w.multiplier}`, 190, 27);
      c.font = font(14);
      c.fillStyle = COLORS.dim;
      c.fillText(`combo ${w.streak}`, 240, 28);
      if (best) c.fillText(`best ${best.toLocaleString()}`, 340, 28);
      if (muted) c.fillText('muted', 450, 28);

      for (let i = 0; i < w.maxLives; i++) {
        const cx = WIDTH - 24 - i * 26;
        c.beginPath();
        c.moveTo(cx, 18); c.lineTo(cx + 9, 28); c.lineTo(cx, 38); c.lineTo(cx - 9, 28); c.closePath();
        if (i < w.lives) { c.fillStyle = COLORS.danger; c.fill(); }
        else { c.strokeStyle = '#503246'; c.lineWidth = 2; c.stroke(); }
      }

      c.fillStyle = '#282346';
      c.fillRect(0, TOP_MARGIN - 4, WIDTH, 4);
      c.fillStyle = COLORS.accent;
      c.fillRect(0, TOP_MARGIN - 4, WIDTH * w.progress, 4);
    }
  }

  function roundRect(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
    c.fill();
  }

  // ------------------------------------------------------------ app

  const $ = (id) => document.getElementById(id);
  const api = {
    async json(url, opts) {
      const res = await fetch(url, opts);
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`);
      return body;
    },
  };

  const params = new URLSearchParams(location.search);
  const state = {
    screen: 'menu', // menu | loading | playing | paused | results
    songs: [],
    selected: null,
    difficulty: localStorageGet('difficulty') || 'normal',
    loaded: null, // { file, song }
    world: null,
    best: 0,
    keys: new Set(),
    pointerY: null, // game-space height of the mouse/trackpad/finger; null = keyboard control
    t: 0,
    lastFrame: performance.now(),
    autoplay: params.has('autoplay'),
    latency: 0, // ms, see setLatency
  };
  const audio = new Audio();
  const renderer = new Renderer($('game'));
  const audioCache = new Map();
  window.addEventListener('resize', () => renderer.resize());

  function localStorageGet(k) { try { return localStorage.getItem('pitch_dodge.' + k); } catch (e) { return null; } }
  function localStorageSet(k, v) { try { localStorage.setItem('pitch_dodge.' + k, v); } catch (e) { /* ignore */ } }

  function setStatus(msg, error = false) {
    $('status').textContent = msg;
    $('status').classList.toggle('error', error);
  }

  function show(screen) {
    state.screen = screen;
    document.body.classList.toggle('playing', screen === 'playing');
    $('menu').classList.toggle('hidden', !(screen === 'menu' || screen === 'loading'));
    $('paused').classList.toggle('hidden', screen !== 'paused');
    $('results').classList.toggle('hidden', screen !== 'results');
    $('calibrate').classList.toggle('hidden', screen !== 'calibrate');
    $('play').disabled = screen === 'loading' || !state.selected;
  }

  // ---------------- menu

  async function refreshSongs(select, { quiet = false } = {}) {
    try {
      const { songs } = await api.json('/api/songs');
      state.songs = songs;
      const remembered = select || localStorageGet('song');
      state.selected = songs.find((s) => s.file === remembered) || songs[0] || null;
      if (quiet && state.screen !== 'menu') return;
      renderSongs();
      if (!songs.length) setStatus('No songs yet: drop one onto the page.');
    } catch (e) {
      if (!quiet) setStatus(`Can't reach the server: ${e.message}`, true);
    }
  }

  function renderSongs() {
    const ul = $('songs');
    ul.innerHTML = '';
    for (const s of state.songs) {
      const li = document.createElement('li');
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', String(state.selected && s.file === state.selected.file));
      li.innerHTML = '<span></span><small></small>';
      li.firstChild.textContent = s.name;
      const badge = { ready: '✓ ready', analysing: 'analysing…', queued: 'queued', error: "can't read" }[s.status];
      li.lastChild.textContent = [s.bundled ? 'bundled' : '', badge || ''].filter(Boolean).join(' · ');
      if (s.status === 'error') li.classList.add('error');
      li.addEventListener('click', () => selectSong(s));
      li.addEventListener('dblclick', () => { selectSong(s); start(); });
      ul.appendChild(li);
    }
    show(state.screen);
    refreshBest();
  }

  function selectSong(s) {
    state.selected = s;
    localStorageSet('song', s.file);
    renderSongs();
  }

  function renderDifficulty() {
    for (const b of document.querySelectorAll('#difficulty button')) {
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', String(b.dataset.d === state.difficulty));
    }
    refreshBest();
  }

  function setDifficulty(d) {
    state.difficulty = d;
    localStorageSet('difficulty', d);
    renderDifficulty();
  }

  async function refreshBest() {
    if (!state.selected) { $('best').textContent = ''; state.best = 0; return; }
    const song = state.selected.name;
    const diff = state.difficulty;
    try {
      const { top } = await api.json(`/api/scores?song=${encodeURIComponent(song)}&difficulty=${diff}`);
      if (state.selected && state.selected.name === song && state.difficulty === diff) {
        state.best = top.length ? top[0].score : 0;
        $('best').textContent = state.best ? `best: ${state.best.toLocaleString()}` : '';
      }
    } catch (e) { /* scores are optional */ }
  }

  async function upload(file) {
    setStatus(`Uploading ${file.name}…`);
    try {
      const res = await api.json('/api/songs', {
        method: 'POST',
        headers: { 'X-Filename': encodeURIComponent(file.name) },
        body: file,
      });
      setStatus(`Added ${res.name}.`);
      await refreshSongs(res.file);
    } catch (e) {
      setStatus(`Upload failed: ${e.message}`, true);
    }
  }

  // ---------------- game flow

  /** Show analysis progress for a song while it loads; returns a function that stops it. */
  function trackProgress(sel, enc) {
    const bar = $('load-progress');
    let stopped = false;
    const paint = (st) => {
      if (stopped) return;
      if (st.state === 'ready') {
        bar.classList.add('hidden');
        setStatus(`Loading ${sel.name}…`);
        return;
      }
      bar.classList.remove('hidden');
      bar.value = st.progress || 0;
      const pct = Math.round((st.progress || 0) * 100);
      setStatus(st.state === 'analysing'
        ? `Analysing ${sel.name}… ${pct}% (only the first time)`
        : `Waiting to analyse ${sel.name}…`);
    };
    const poll = async () => {
      while (!stopped) {
        try { paint(await api.json(`/api/songs/${enc}/status`)); } catch (e) { /* keep trying */ }
        await new Promise((r) => setTimeout(r, 250));
      }
    };
    poll();
    return () => { stopped = true; bar.classList.add('hidden'); };
  }

  // Keep the song list's ready/analysing badges fresh while songs analyse in the background.
  setInterval(() => {
    if (state.screen !== 'menu') return;
    if (state.songs.some((s) => s.status === 'queued' || s.status === 'analysing')) {
      refreshSongs(state.selected && state.selected.file, { quiet: true });
    }
  }, 1500);

  async function start() {
    if (!state.selected || state.screen === 'loading') return;
    const sel = state.selected;
    audio.ensure(); // must happen inside the key/click gesture
    if (audio.ctx.state === 'suspended') audio.ctx.resume();
    try {
      if (!state.loaded || state.loaded.file !== sel.file) {
        show('loading');
        const enc = encodeURIComponent(sel.file);
        const stopProgress = trackProgress(sel, enc);
        const [data, buf] = await Promise.all([
          api.json(`/api/songs/${enc}/analysis`).finally(stopProgress),
          audioCache.get(sel.file) || fetch(`/api/songs/${enc}/audio`).then((r) => {
            if (!r.ok) throw new Error(`audio: ${r.status}`);
            return r.arrayBuffer();
          }),
        ]);
        setStatus('Decoding audio…');
        await audio.load(buf);
        state.loaded = { file: sel.file, song: new Song(data) };
        setStatus('');
      }
    } catch (e) {
      show('menu');
      setStatus(`Couldn't load ${sel.name}: ${e.message}`, true);
      return;
    }
    state.pointerY = null; // start under keyboard control until the pointer moves
    state.world = new World(state.loaded.song, state.loaded.song.charts[state.difficulty]);
    renderer.clearEffects();
    await audio.play(state.world.chart.count_in);
    show('playing');
  }

  async function pause() {
    if (state.screen !== 'playing') return;
    await audio.pause();
    show('paused');
  }

  async function resume() {
    if (state.screen !== 'paused') return;
    await audio.resume();
    show('playing');
  }

  function toMenu() {
    audio.stop();
    audio.resume();
    show('menu');
    refreshSongs(state.selected && state.selected.file, { quiet: true }); // badges may have changed
    refreshBest();
  }

  async function finish() {
    const w = state.world;
    audio.stop();
    show('results');
    $('results-title').textContent = w.cleared ? 'SONG CLEARED' : 'GAME OVER';
    $('results-title').style.color = w.cleared ? COLORS.accent : COLORS.danger;
    $('results-score').textContent = w.score.toLocaleString();
    const stats = [
      ['caught', `${w.caught} (${w.perfect} perfect)`], ['missed', w.missed],
      ['accuracy', `${Math.round(w.accuracy * 100)}%`], ['hazards hit', w.hits],
      ['holds', `${w.holdsCompleted} / ${w.holds}`],
      ['best combo', w.bestStreak], ['song', `${Math.round(w.progress * 100)}%`],
    ];
    $('results-stats').innerHTML = '';
    for (const [k, v] of stats) {
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd'); dd.textContent = v;
      $('results-stats').append(dt, dd);
    }
    $('results-rank').textContent = '';
    try {
      const res = await api.json('/api/scores', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ song: state.selected.name, difficulty: state.difficulty,
                               score: w.score, best_streak: w.bestStreak, cleared: w.cleared }),
      });
      state.best = res.top.length ? res.top[0].score : w.score;
      $('results-rank').textContent = res.rank === 1 ? 'NEW HIGH SCORE!'
        : res.rank ? `#${res.rank} on the board (best ${state.best.toLocaleString()})`
        : `best ${state.best.toLocaleString()}`;
    } catch (e) { /* offline scores are fine */ }
  }

  function toggleMute() {
    audio.setMuted(!audio.muted);
    localStorageSet('muted', audio.muted ? '1' : '');
  }

  // ---------------- audio delay (latency) calibration

  const CALIBRATE = { clicks: 16, interval: 0.6, skip: 4, minTaps: 6 };
  const LATENCY_MIN = -100, LATENCY_MAX = 400;
  const cal = { running: false, clicks: [], taps: [], result: null, endAt: 0 };

  function setLatency(ms) {
    ms = clamp(Math.round(ms / 5) * 5, LATENCY_MIN, LATENCY_MAX);
    state.latency = ms;
    audio.offset = ms / 1000;
    $('latency').value = String(ms);
    $('latency-value').textContent = `${ms > 0 ? '+' : ''}${ms} ms`;
    localStorageSet('latency', String(ms));
  }

  /**
   * Median of (tap - click - reported output latency) for taps matched to a
   * click, ignoring the first few clicks while the player finds the beat.
   * Whatever the browser already reports as output latency is compensated
   * automatically, so this is only the remainder.
   */
  function measureOffset(clicks, taps, outputLatency) {
    const diffs = [];
    for (const tap of taps) {
      let best = -1;
      for (let i = 0; i < clicks.length; i++) {
        if (best < 0 || Math.abs(tap - clicks[i]) < Math.abs(tap - clicks[best])) best = i;
      }
      // A tap belongs to the click before it if it's late, so allow up to most of an interval.
      if (best >= CALIBRATE.skip && Math.abs(tap - clicks[best]) < CALIBRATE.interval * 0.8) {
        diffs.push(tap - clicks[best] - outputLatency);
      }
    }
    if (diffs.length < CALIBRATE.minTaps) return null;
    diffs.sort((a, b) => a - b);
    const mid = diffs.length >> 1;
    const median = diffs.length % 2 ? diffs[mid] : (diffs[mid - 1] + diffs[mid]) / 2;
    return median * 1000;
  }

  function openCalibration() {
    cal.running = false;
    cal.result = null;
    $('calibrate-dots').textContent = '';
    $('calibrate-result').textContent = '';
    $('calibrate-hint').textContent = `Current delay: ${state.latency} ms`;
    $('calibrate-start').classList.remove('hidden');
    $('calibrate-save').classList.add('hidden');
    show('calibrate');
  }

  async function startCalibration() {
    const ctx = audio.ensure();
    if (ctx.state === 'suspended') await ctx.resume();
    audio.stop();
    const t0 = ctx.currentTime + 0.6;
    cal.clicks = [];
    cal.taps = [];
    for (let i = 0; i < CALIBRATE.clicks; i++) {
      const t = t0 + i * CALIBRATE.interval;
      cal.clicks.push(t);
      audio.click(t, i % 4 === 0);
    }
    cal.endAt = cal.clicks[cal.clicks.length - 1] + 0.8;
    cal.running = true;
    cal.result = null;
    $('calibrate-result').textContent = '';
    $('calibrate-hint').textContent = 'Listen, then tap along…';
    $('calibrate-start').classList.add('hidden');
    $('calibrate-save').classList.add('hidden');
  }

  function calibrationTap() {
    if (!cal.running) return;
    cal.taps.push(audio.ctx.currentTime);
  }

  function tickCalibration() {
    if (!cal.running) return;
    const now = audio.ctx.currentTime - (audio.ctx.outputLatency || 0);
    const heard = cal.clicks.filter((c) => c <= now).length;
    $('calibrate-dots').textContent = '●'.repeat(heard) + '○'.repeat(CALIBRATE.clicks - heard);
    if (audio.ctx.currentTime < cal.endAt) return;
    cal.running = false;
    const ms = measureOffset(cal.clicks, cal.taps, audio.ctx.outputLatency || 0);
    $('calibrate-start').classList.remove('hidden');
    $('calibrate-start').firstChild.textContent = 'Try again ';
    if (ms == null) {
      $('calibrate-hint').textContent = 'Not enough taps landed near the clicks. Try again?';
      return;
    }
    cal.result = clamp(Math.round(ms / 5) * 5, LATENCY_MIN, LATENCY_MAX);
    $('calibrate-result').textContent = `${cal.result > 0 ? '+' : ''}${cal.result} ms`;
    $('calibrate-hint').textContent = 'Use this delay? (Enter)';
    $('calibrate-save').classList.remove('hidden');
  }

  function saveCalibration() {
    if (cal.result == null) return;
    setLatency(cal.result);
    toMenu();
  }

  $('latency').addEventListener('input', (e) => setLatency(Number(e.target.value)));
  $('calibrate-open').addEventListener('click', openCalibration);
  $('calibrate-start').addEventListener('click', startCalibration);
  $('calibrate-save').addEventListener('click', saveCalibration);
  $('calibrate-cancel').addEventListener('click', () => { cal.running = false; toMenu(); });

  // ---------------- input

  function direction() {
    if (state.autoplay) return botDirection();
    const k = state.keys;
    const up = k.has('ArrowUp') || k.has('KeyW');
    const down = k.has('ArrowDown') || k.has('KeyS');
    if (up || down) state.pointerY = null; // keys take over until the pointer moves again
    return (down ? 1 : 0) - (up ? 1 : 0);
  }

  /** Mouse, trackpad or touch: the paddle follows the pointer's height over the game. */
  function onPointer(e) {
    const rect = $('game').getBoundingClientRect();
    if (!rect.height) return;
    state.pointerY = ((e.clientY - rect.top) / rect.height) * HEIGHT;
  }
  window.addEventListener('pointermove', onPointer);
  window.addEventListener('pointerdown', (e) => { if (state.screen === 'playing') onPointer(e); });

  /** Chase the next catch note, sidestepping hazards (for demos and tests: ?autoplay). */
  function botDirection() {
    const p = state.world.paddle;
    const ahead = state.world.notes.filter((n) => !n.passed && n.x < p.x + p.width);
    const catches = ahead.filter((n) => n.kind === 'catch').sort((a, b) => a.t - b.t);
    let target = catches.length ? catches[0].y : p.y;
    for (const h of ahead) {
      if (h.kind !== 'hazard' || p.x - h.x > 120) continue;
      const clear = p.height / 2 + h.radius * 1.5 + 8;
      if (Math.abs(h.y - target) < clear - 2) target = h.y + (target >= h.y ? 1 : -1) * clear;
    }
    const d = target - p.y;
    return Math.abs(d) < 3 ? 0 : Math.sign(d);
  }


  window.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const code = e.code;
    if (['ArrowUp', 'ArrowDown', 'Space'].includes(code)) e.preventDefault();
    state.keys.add(code);
    if (e.repeat) return;

    if (code === 'KeyM') return toggleMute();
    switch (state.screen) {
      case 'calibrate':
        if (code === 'Space') (cal.running ? calibrationTap() : startCalibration());
        else if (code === 'Enter') saveCalibration();
        else if (code === 'Escape') { cal.running = false; toMenu(); }
        break;
      case 'menu':
        if (code === 'Space' || code === 'Enter') start();
        else if (code === 'ArrowLeft' || code === 'ArrowRight') {
          const i = DIFFICULTY_ORDER.indexOf(state.difficulty) + (code === 'ArrowLeft' ? -1 : 1);
          setDifficulty(DIFFICULTY_ORDER[(i + 3) % 3]);
        } else if (code === 'ArrowUp' || code === 'ArrowDown') {
          if (!state.songs.length) break;
          const i = state.songs.findIndex((s) => state.selected && s.file === state.selected.file);
          const j = clamp(i + (code === 'ArrowUp' ? -1 : 1), 0, state.songs.length - 1);
          selectSong(state.songs[j]);
        }
        break;
      case 'playing':
        if (code === 'KeyP' || code === 'Escape') pause();
        else if (code === 'KeyR') start();
        break;
      case 'paused':
        if (code === 'KeyP' || code === 'Escape' || code === 'Space') resume();
        else if (code === 'KeyR') { audio.resume(); start(); }
        else if (code === 'KeyQ') toMenu();
        break;
      case 'results':
        if (code === 'KeyR' || code === 'Space') start();
        else if (code === 'Enter' || code === 'Escape') toMenu();
        break;
    }
  });
  window.addEventListener('keyup', (e) => state.keys.delete(e.code));
  window.addEventListener('blur', () => { state.keys.clear(); pause(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });

  for (const b of document.querySelectorAll('#difficulty button')) {
    b.addEventListener('click', () => setDifficulty(b.dataset.d));
  }
  $('play').addEventListener('click', start);
  document.addEventListener('click', (e) => {
    const a = e.target.closest('[data-action]');
    if (!a) return;
    const action = a.dataset.action;
    if (action === 'resume') resume();
    else if (action === 'restart') { audio.resume(); start(); }
    else if (action === 'menu') toMenu();
  });

  $('file').addEventListener('change', (e) => { if (e.target.files[0]) upload(e.target.files[0]); e.target.value = ''; });
  let dragDepth = 0;
  window.addEventListener('dragenter', (e) => { e.preventDefault(); dragDepth++; document.body.classList.add('dragging'); });
  window.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove('dragging'); } });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    dragDepth = 0;
    document.body.classList.remove('dragging');
    const file = e.dataTransfer.files[0];
    if (file && (state.screen === 'menu' || state.screen === 'results')) {
      if (state.screen === 'results') toMenu();
      upload(file);
    }
  });

  // ---------------- loop

  function frame(now) {
    const frameDt = Math.min((now - state.lastFrame) / 1000, MAX_FRAME);
    state.lastFrame = now;
    state.t += frameDt;
    if (state.screen === 'calibrate') tickCalibration();

    if (state.screen === 'playing') {
      const w = state.world;
      const songTime = audio.position();
      const dt = clamp(songTime - w.songTime, 0, MAX_FRAME);
      const dir = direction();
      const events = w.update(songTime, dt, dir, state.autoplay ? null : state.pointerY);
      renderer.react(events);
      for (const e of events) audio.sfx(e.kind, e.midi, e.value);
      if (w.over || w.cleared) finish();
    }
    if (state.screen !== 'paused') renderer.tick(frameDt);

    if (state.world && !['menu', 'loading', 'calibrate'].includes(state.screen)) {
      renderer.worldScene(state.world);
      renderer.hud(state.world, state.best, audio.muted);
    } else {
      renderer.titleScene(state.t);
    }
    requestAnimationFrame(frame);
  }

  // Exposed for tests and the curious.
  window.PitchDodge = { state, World, Song, measureOffset, audio, cal };

  audio.setMuted(!!localStorageGet('muted'));
  setLatency(Number(localStorageGet('latency') || 0));
  renderDifficulty();
  show('menu');
  refreshSongs();
  requestAnimationFrame(frame);
})();
