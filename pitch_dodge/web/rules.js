/*
 * Pitch Dodge game rules for the browser: a mirror of pitch_dodge/world.py and
 * the geometry in pitch_dodge/config.py. Keep them in step;
 * tests/test_js_parity.py runs both on the same chart and compares results.
 *
 * Loaded by the page as a plain script (window.PitchDodgeRules) and by Node
 * for tests (module.exports). No DOM access in here.
 */
(function (root) {
  'use strict';


  const WIDTH = 960;
  const HEIGHT = 600;
  const TOP_MARGIN = 56;
  const SPAWN_MARGIN = 30;

  const DIFFICULTY_ORDER = ['easy', 'normal', 'hard'];

  const PADDLE_WIDTH = 14;
  const PADDLE_X = WIDTH - 110;
  const PADDLE_SPEED = 560;
  const POINTER_SPEED = 1500; // cap when following the mouse / trackpad / touch
  const NOTE_RADIUS = 9;
  const INVULNERABLE_FOR = 1.0;
  const POINTS_CATCH = 10;
  const POINTS_PERFECT = 15;
  const PERFECT_FRACTION = 0.3;
  const STREAK_PER_LEVEL = 10;
  const MAX_MULTIPLIER = 8;
  const POINTS_PER_LIFE_LEFT = 250;
  const POINTS_HOLD_PER_SECOND = 20;
  const POINTS_HOLD_BONUS = 10;
  const MAX_FRAME = 1 / 20;

  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

  function pitchToY(pitch) {
    const top = TOP_MARGIN + SPAWN_MARGIN;
    const bottom = HEIGHT - SPAWN_MARGIN;
    return bottom - clamp(pitch, 0, 1) * (bottom - top);
  }

  class Song {
    constructor(data) {
      this.pitch = Float32Array.from(data.pitch);
      this.energy = Float32Array.from(data.energy);
      this.hop = data.hop_seconds;
      this.duration = data.duration;
      this.charts = data.charts;
    }
    frame(t) { return clamp(Math.floor(t / this.hop), 0, this.pitch.length - 1); }
    pitchAt(t) { return this.pitch[this.frame(t)]; }
    energyAt(t) { return t < 0 ? 0 : this.energy[this.frame(t)]; }
  }

  /**
   * Plays a chart from the server (see chart.py). A note's position comes
   * straight from song time, x = PADDLE_X - (arrival - now) * speed, so it
   * crosses the paddle exactly on its beat whatever the frame rate.
   */
  class World {
    constructor(song, chart) {
      this.song = song;
      this.chart = chart;
      this.notes = [];
      this.score = 0;
      this.streak = 0; // combo
      this.bestStreak = 0;
      this.caught = 0;
      this.perfect = 0;
      this.missed = 0;
      this.hits = 0; // hazards that hit
      this.holds = 0;
      this.holdsCompleted = 0;
      this.songTime = -chart.count_in;
      this.invulnerableUntil = -1e9;
      this.over = false;
      this.cleared = false;
      this.maxLives = chart.lives;
      this.lives = chart.lives;
      this.paddle = { x: PADDLE_X, y: (TOP_MARGIN + HEIGHT) / 2, width: PADDLE_WIDTH, height: chart.paddle_height };
      this.next = 0;
    }

    get duration() { return this.chart.duration; }
    get progress() { return this.duration <= 0 ? 1 : clamp(this.songTime / this.duration, 0, 1); }
    get multiplier() { return Math.min(1 + Math.floor(this.streak / STREAK_PER_LEVEL), MAX_MULTIPLIER); }
    get invulnerable() { return this.songTime < this.invulnerableUntil; }
    get speed() { return this.chart.speed; }
    get accuracy() { const n = this.caught + this.missed; return n ? this.caught / n : 0; }

    xAt(noteT, now) { return PADDLE_X - (noteT - now) * this.chart.speed; }

    movePaddle(direction, dt, targetY) {
      const p = this.paddle;
      const y = targetY == null
        ? p.y + direction * PADDLE_SPEED * dt
        : p.y + clamp(targetY - p.y, -POINTER_SPEED * dt, POINTER_SPEED * dt);
      p.y = clamp(y, TOP_MARGIN + p.height / 2, HEIGHT - p.height / 2);
    }

    gapY(note) {
      const p = this.paddle;
      return Math.max(p.y - p.height / 2 - note.y, note.y - (p.y + p.height / 2), 0) - note.radius;
    }

    /** Advance to songTime. The paddle follows targetY (a pointer) if given, else moves by direction. */
    update(songTime, dt, direction, targetY = null) {
      const events = [];
      if (this.over || this.cleared) return events;
      const prev = this.songTime;
      this.songTime = songTime;
      this.movePaddle(direction, dt, targetY);

      const notes = this.chart.notes;
      while (this.next < notes.length && notes[this.next].t - this.chart.travel_time <= songTime) {
        const c = notes[this.next++];
        const n = { t: c.t, y: pitchToY(c.pitch), pitch: c.pitch, kind: c.kind, strength: c.strength, midi: c.midi,
                    radius: NOTE_RADIUS * (0.85 + 0.4 * c.strength), x: -NOTE_RADIUS,
                    duration: c.duration || 0, passed: false, hit: false,
                    holding: false, holdBroken: false, holdPoints: 0 };
        this.notes.push(n);
        events.push({ kind: 'spawn', x: 0, y: n.y });
      }

      for (const n of this.notes) {
        this.step(n, prev, songTime, events);
        if (this.over) return events;
      }
      const speed = this.chart.speed;
      this.notes = this.notes.filter((n) => !(n.hit && !n.holding) && n.x - n.duration * speed - n.radius < WIDTH);

      if (songTime >= this.duration && this.next >= notes.length && this.notes.length === 0) {
        this.cleared = true;
        const bonus = this.lives * POINTS_PER_LIFE_LEFT;
        this.score += bonus;
        events.push({ kind: 'cleared', value: bonus });
      }
      return events;
    }

    step(n, prev, now, events) {
      const xPrev = this.xAt(n.t, prev);
      n.x = this.xAt(n.t, now);
      if (n.holding) { this.hold(n, prev, now, events); return; }
      if (n.passed) return;
      const p = this.paddle;
      const crossing = xPrev - n.radius <= p.x + p.width && n.x + n.radius >= p.x;
      const touching = crossing && this.gapY(n) < 0;
      const gone = n.x - n.radius > p.x + p.width;
      if (n.kind === 'hazard') {
        if (touching && !this.invulnerable) this.hurt(n, events);
        else if (gone) n.passed = true;
      } else if (touching) {
        this.catch(n, events);
      } else if (gone) {
        n.passed = true;
        this.missed++;
        this.streak = 0;
        events.push({ kind: 'miss', x: n.x, y: n.y });
      }
    }

    catch(n, events) {
      n.hit = n.passed = true;
      const oldLevel = this.multiplier;
      const perfect = Math.abs(n.y - this.paddle.y) <= (this.paddle.height / 2) * PERFECT_FRACTION;
      this.caught++;
      if (perfect) this.perfect++;
      this.streak++;
      this.bestStreak = Math.max(this.bestStreak, this.streak);
      const points = (perfect ? POINTS_PERFECT : POINTS_CATCH) * oldLevel;
      this.score += points;
      events.push({ kind: perfect ? 'perfect' : 'catch', x: n.x, y: n.y, value: points, midi: n.midi });
      if (n.duration > 0) {
        n.holding = true;
        this.holds++;
        events.push({ kind: 'hold_start', x: n.x, y: n.y, value: Math.round(n.duration * 1000), midi: n.midi });
      }
      if (this.multiplier > oldLevel) {
        events.push({ kind: 'level_up', x: n.x, y: n.y, value: this.multiplier, midi: n.midi });
      }
    }

    /** Score while the paddle stays on a hold note's tail. */
    hold(n, prev, now, events) {
      const end = n.t + n.duration;
      const overlap = Math.max(0, Math.min(now, end) - Math.max(prev, n.t));
      const p = this.paddle;
      if (this.gapY(n) < 0) {
        const before = Math.floor(n.holdPoints);
        n.holdPoints += POINTS_HOLD_PER_SECOND * this.multiplier * overlap;
        this.score += Math.floor(n.holdPoints) - before;
      } else if (!n.holdBroken && overlap > 0) {
        n.holdBroken = true;
        events.push({ kind: 'hold_break', x: p.x, y: n.y, midi: n.midi });
      }
      if (now >= end) {
        n.holding = false;
        if (!n.holdBroken) {
          const bonus = POINTS_HOLD_BONUS * this.multiplier;
          this.score += bonus;
          this.holdsCompleted++;
          events.push({ kind: 'hold_done', x: p.x, y: n.y, value: bonus, midi: n.midi });
        }
      }
    }

    hurt(n, events) {
      n.hit = n.passed = true;
      this.hits++;
      this.lives--;
      this.streak = 0;
      this.invulnerableUntil = this.songTime + INVULNERABLE_FOR;
      events.push({ kind: 'hit', x: n.x, y: n.y, value: this.lives });
      if (this.lives <= 0) {
        this.over = true;
        events.push({ kind: 'game_over', value: this.score });
      }
    }
  }

  const api = {
    WIDTH, HEIGHT, TOP_MARGIN, SPAWN_MARGIN, DIFFICULTY_ORDER, PADDLE_WIDTH, PADDLE_X, PADDLE_SPEED,
    POINTER_SPEED, NOTE_RADIUS, MAX_FRAME, clamp, pitchToY, Song, World,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PitchDodgeRules = api;
})(typeof window !== 'undefined' ? window : globalThis);
