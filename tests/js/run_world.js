// Play a chart through the browser rules with scripted input; print the outcome as JSON.
// Usage: node tests/js/run_world.js input.json   (see tests/test_js_parity.py)
const fs = require('fs');
const path = require('path');
const { World } = require(path.join(__dirname, '..', '..', 'pitch_dodge', 'web', 'rules.js'));

const { chart, inputs } = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const w = new World(null, chart);
const events = [];
for (const [t, dt, direction, target] of inputs) {
  for (const e of w.update(t, dt, direction, target)) events.push([e.kind, e.value || 0]);
}
process.stdout.write(JSON.stringify({
  score: w.score, caught: w.caught, perfect: w.perfect, missed: w.missed, hits: w.hits,
  holds: w.holds, holds_completed: w.holdsCompleted, lives: w.lives, over: w.over, cleared: w.cleared,
  paddle_y: Math.round(w.paddle.y * 1000) / 1000, events,
}));
