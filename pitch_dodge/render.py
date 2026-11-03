"""Everything that draws. Reads the World; never changes the rules."""

from __future__ import annotations

import bisect
import colorsys
import math
import random
from dataclasses import dataclass

import pygame

from .world import HEIGHT, TOP_MARGIN, WIDTH, Event, World, pitch_to_y

BG_TOP = (10, 8, 24)
BG_BOTTOM = (24, 10, 40)
TEXT = (235, 235, 245)
DIM = (140, 135, 170)
ACCENT = (120, 255, 170)
DANGER = (255, 80, 100)
GOLD = (255, 210, 90)


def beat_pulse(beats: list[float], t: float) -> float:
    """1 on a beat, decaying to 0 before the next; downbeats (every 4th) hit harder."""
    i = bisect.bisect_right(beats, t) - 1
    if i < 0 or t < 0:
        return 0.0
    return (1.0 if i % 4 == 0 else 0.6) * math.exp(-(t - beats[i]) * 8)


def pitch_color(pitch: float) -> tuple[int, int, int]:
    """Low notes are warm, high notes are cool."""
    hue = 0.02 + 0.7 * min(max(pitch, 0.0), 1.0)
    r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: tuple[int, int, int]
    size: float


@dataclass
class Popup:
    text: str
    x: float
    y: float
    life: float
    color: tuple[int, int, int]
    judge: bool = False


class Renderer:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.font_big = pygame.font.Font(None, 84)
        self.font_mid = pygame.font.Font(None, 44)
        self.font = pygame.font.Font(None, 30)
        self.font_small = pygame.font.Font(None, 22)
        self.background = self._gradient()
        self.particles: list[Particle] = []
        self.popups: list[Popup] = []
        self.shake = 0.0
        self.flash = 0.0
        self._glow_cache: dict[tuple, pygame.Surface] = {}
        self.rng = random.Random()

    # ------------------------------------------------------------ helpers

    def _gradient(self) -> pygame.Surface:
        surf = pygame.Surface((WIDTH, HEIGHT))
        for y in range(HEIGHT):
            t = y / HEIGHT
            c = [int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM, strict=True)]
            pygame.draw.line(surf, c, (0, y), (WIDTH, y))
        return surf

    def _glow(self, color: tuple[int, int, int], radius: int) -> pygame.Surface:
        key = (color[0] // 8, color[1] // 8, color[2] // 8, radius)
        surf = self._glow_cache.get(key)
        if surf is None:
            size = radius * 6
            surf = pygame.Surface((size, size), pygame.SRCALPHA)
            for i in range(10, 0, -1):
                r = radius * (1 + i * 0.2)
                alpha = int(14 * (11 - i) / 10)
                pygame.draw.circle(surf, (*color, alpha), (size // 2, size // 2), int(r))
            pygame.draw.circle(surf, (*color, 255), (size // 2, size // 2), radius)
            pygame.draw.circle(surf, (255, 255, 255, 200), (size // 2, size // 2), max(2, radius // 2))
            self._glow_cache[key] = surf
        return surf

    def text(self, font, s, color, center=None, topleft=None, topright=None, alpha=255):
        img = font.render(s, True, color)
        if alpha < 255:
            img.set_alpha(alpha)
        rect = img.get_rect()
        if center:
            rect.center = center
        elif topleft:
            rect.topleft = topleft
        elif topright:
            rect.topright = topright
        self.screen.blit(img, rect)
        return rect

    def _burst(self, x, y, color, n, speed, life=0.6, size=3.0):
        for _ in range(n):
            a = self.rng.uniform(0, math.tau)
            s = self.rng.uniform(0.3, 1.0) * speed
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s, life, life, color, size))

    # ------------------------------------------------------------ effects

    def react(self, events: list[Event]) -> None:
        for e in events:
            if e.kind == "hit":
                self._burst(e.x, e.y, DANGER, 40, 420, life=0.8, size=4)
                self.shake = 0.35
                self.flash = 0.25
                self.popups.append(Popup("OUCH", e.x - 110, e.y - 20, 0.8, DANGER))
            elif e.kind == "perfect":
                self._burst(e.x, e.y, GOLD, 18, 240)
                self._judge(f"PERFECT +{e.value}", e.x - 170, e.y - 26, GOLD)
            elif e.kind == "catch":
                self._burst(e.x, e.y, ACCENT, 10, 180, life=0.5, size=3)
            elif e.kind == "miss":
                self._burst(e.x, e.y, DIM, 6, 80, life=0.4, size=2)
                self._judge("miss", e.x - 70, e.y - 20, DIM)
            elif e.kind == "level_up":
                self.popups.append(Popup(f"x{e.value}!", WIDTH / 2 - 30, HEIGHT / 2 - 40, 1.0, ACCENT))
            elif e.kind == "spawn":
                self._burst(6, e.y, TEXT, 4, 90, life=0.3, size=2)

    def _judge(self, text, x, y, color) -> None:
        """Catch/miss labels replace each other instead of piling up."""
        self.popups = [p for p in self.popups if not p.judge]
        self.popups.append(Popup(text, x, y, 0.45, color, judge=True))

    def tick(self, dt: float) -> None:
        for p in self.particles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vx *= 0.92
            p.vy = p.vy * 0.92 + 300 * dt
            p.life -= dt
        self.particles = [p for p in self.particles if p.life > 0]
        for p in self.popups:
            p.y -= 40 * dt
            p.life -= dt
        self.popups = [p for p in self.popups if p.life > 0]
        self.shake = max(0.0, self.shake - dt)
        self.flash = max(0.0, self.flash - dt)

    def clear_effects(self) -> None:
        self.particles.clear()
        self.popups.clear()
        self.shake = self.flash = 0.0

    # ------------------------------------------------------------ scenes

    def draw_background(self, world: World | None, song=None, t: float = 0.0) -> None:
        self.screen.blit(self.background, (0, 0))
        if world is None or song is None:
            return
        energy = song.energy_at(t) if t >= 0 else 0.0
        # Faint grid that pulses with loudness.
        grid = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        alpha = int(10 + 30 * energy)
        for x in range(0, WIDTH, 48):
            pygame.draw.line(grid, (120, 90, 220, alpha), (x, TOP_MARGIN), (x, HEIGHT))
        for y in range(TOP_MARGIN, HEIGHT, 48):
            pygame.draw.line(grid, (120, 90, 220, alpha), (0, y), (WIDTH, y))
        self.screen.blit(grid, (0, 0))

        speed = world.speed
        px = world.paddle.x

        # Upcoming beats as lines scrolling toward the paddle (every 4th brighter).
        lines = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        for i, b in enumerate(world.chart.beats):
            x = px - (b - t) * speed
            if x < 0:
                break
            if x <= px + 4:
                alpha = 40 if i % 4 == 0 else 18
                pygame.draw.rect(
                    lines, (160, 140, 255, alpha), (int(x) - 1, TOP_MARGIN, 2, HEIGHT - TOP_MARGIN)
                )
        self.screen.blit(lines, (0, 0))

        # The melody path: a line through the upcoming catch notes, where they will be.
        pts = []
        for n in world.chart.notes:
            if n.kind != "catch":
                continue
            x = world.x_at(n.t, t)
            if x > px + 40:
                continue
            pts.append((x, pitch_to_y(n.pitch)))
            if x < -40:
                break
        if len(pts) > 1:
            pygame.draw.lines(self.screen, (90, 70, 160), False, pts, 2)

        # Emitter: the pitch of what's arriving one travel time from now.
        ahead = t + world.chart.travel_time
        if 0 <= ahead <= world.duration:
            pitch = song.pitch_at(ahead)
            g = self._glow(pitch_color(pitch), 7 + int(5 * energy))
            self.screen.blit(g, g.get_rect(center=(4, pitch_to_y(pitch))))

        if t < 0:  # count-in
            self.text(self.font_big, str(int(-t) + 1), TEXT, center=(WIDTH / 2, HEIGHT / 2), alpha=150)

    def _draw_hazard(self, x: float, y: float, r: float, t: float) -> None:
        spin = t * 3
        pts = []
        for i in range(16):
            a = spin + i * math.tau / 16
            rr = r * (1.0 if i % 2 == 0 else 0.5)
            pts.append((x + math.cos(a) * rr, y + math.sin(a) * rr))
        g = self._glow(DANGER, int(r * 0.6))
        self.screen.blit(g, g.get_rect(center=(int(x), int(y))))
        pygame.draw.polygon(self.screen, DANGER, pts)
        pygame.draw.circle(self.screen, (40, 8, 18), (int(x), int(y)), max(2, int(r * 0.32)))

    def draw_world(self, world: World) -> None:
        # Notes, with a short trail. Hazards are red spiked shapes.
        for n in world.notes:
            if n.kind == "hazard":
                self._draw_hazard(n.x, n.y, n.radius * 1.4, world.song_time)
                continue
            color = pitch_color(n.pitch)
            for i in range(1, 4):
                tx = n.x - i * n.radius * 0.9
                ty = n.y
                fade = [int(c * (0.5 - i * 0.12)) for c in color]
                pygame.draw.circle(self.screen, fade, (int(tx), int(ty)), max(2, int(n.radius - i * 2)))
            g = self._glow(color, int(n.radius))
            self.screen.blit(g, g.get_rect(center=(int(n.x), int(n.y))))

        # Paddle (blinks while invulnerable, glows on the beat).
        p = world.paddle
        pulse = beat_pulse(world.chart.beats, world.song_time)
        visible = not world.invulnerable or int(world.song_time * 12) % 2 == 0
        if visible:
            rect = pygame.Rect(int(p.x), int(p.top), p.width, p.height)
            grow = int(12 + 6 * pulse)
            glow = pygame.Surface((rect.w + 2 * grow, rect.h + 2 * grow), pygame.SRCALPHA)
            pygame.draw.rect(glow, (*ACCENT, int(45 + 75 * pulse)), glow.get_rect(), border_radius=14)
            self.screen.blit(glow, (rect.x - grow, rect.y - grow))
            pygame.draw.rect(self.screen, ACCENT, rect, border_radius=6)
            pygame.draw.rect(self.screen, (220, 255, 230), rect.inflate(-8, -8), border_radius=4)

        for pt in self.particles:
            a = pt.life / pt.max_life
            c = [int(v * a) for v in pt.color]
            pygame.draw.circle(self.screen, c, (int(pt.x), int(pt.y)), max(1, int(pt.size * a + 0.5)))
        for pu in self.popups:
            self.text(
                self.font, pu.text, pu.color, topleft=(pu.x, pu.y), alpha=int(255 * min(1, pu.life * 2))
            )

    def draw_hud(self, world: World, best: int, muted: bool) -> None:
        bar = pygame.Surface((WIDTH, TOP_MARGIN), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 120))
        self.screen.blit(bar, (0, 0))
        pygame.draw.line(self.screen, (60, 50, 100), (0, TOP_MARGIN), (WIDTH, TOP_MARGIN))

        self.text(self.font_mid, f"{world.score:,}", TEXT, topleft=(16, 10))
        mult_color = ACCENT if world.multiplier > 1 else DIM
        self.text(self.font, f"x{world.multiplier}", mult_color, topleft=(190, 18))
        self.text(self.font_small, f"combo {world.streak}", DIM, topleft=(240, 22))
        if best:
            self.text(self.font_small, f"best {best:,}", DIM, topleft=(360, 22))
        if muted:
            self.text(self.font_small, "muted", DIM, topleft=(470, 22))

        # Lives as hearts-ish diamonds.
        for i in range(world.difficulty.lives):
            cx = WIDTH - 24 - i * 26
            pts = [(cx, 18), (cx + 9, 28), (cx, 38), (cx - 9, 28)]
            if i < world.lives:
                pygame.draw.polygon(self.screen, DANGER, pts)
            else:
                pygame.draw.polygon(self.screen, (80, 50, 70), pts, 2)

        # Song progress.
        w = int(WIDTH * world.progress)
        pygame.draw.rect(self.screen, (40, 35, 70), (0, TOP_MARGIN - 4, WIDTH, 4))
        pygame.draw.rect(self.screen, ACCENT, (0, TOP_MARGIN - 4, w, 4))

    def finish_frame(self) -> None:
        """Apply screen shake and hit flash to whatever was drawn this frame."""
        if self.flash > 0:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((255, 40, 60, int(120 * self.flash / 0.25)))
            self.screen.blit(overlay, (0, 0))
        if self.shake > 0:
            mag = 10 * self.shake / 0.35
            dx, dy = self.rng.uniform(-mag, mag), self.rng.uniform(-mag, mag)
            frame = self.screen.copy()
            self.screen.fill(BG_TOP)
            self.screen.blit(frame, (dx, dy))

    def dim(self, alpha: int = 170) -> None:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((5, 4, 15, alpha))
        self.screen.blit(overlay, (0, 0))

    def draw_title(self, song: str, difficulty: str, best: int, t: float) -> None:
        self.screen.blit(self.background, (0, 0))
        # Decorative melody wave.
        pts = [
            (x, HEIGHT * 0.74 + math.sin(x / 70 + t * 2) * 40 + math.sin(x / 23 + t * 3) * 12)
            for x in range(0, WIDTH + 1, 8)
        ]
        pygame.draw.lines(self.screen, (90, 70, 160), False, pts, 3)
        for i in range(7):
            x = (t * 220 + i * 150) % (WIDTH + 100) - 50
            y = HEIGHT * 0.74 + math.sin(x / 70 + t * 2) * 40
            g = self._glow(pitch_color(i / 6), 9)
            self.screen.blit(g, g.get_rect(center=(int(x), int(y))))

        self.text(self.font_big, "PITCH DODGE", TEXT, center=(WIDTH / 2, 130))
        self.text(self.font, "catch the melody, dodge the drums", DIM, center=(WIDTH / 2, 185))
        self.text(self.font, f"song: {song}", TEXT, center=(WIDTH / 2, 250))

        y = 300
        names = ["easy", "normal", "hard"]
        total = sum(self.font_mid.size(n)[0] for n in names) + 60 * (len(names) - 1)
        x = WIDTH / 2 - total / 2
        for n in names:
            w = self.font_mid.size(n)[0]
            color = ACCENT if n == difficulty else DIM
            r = self.text(self.font_mid, n, color, topleft=(x, y))
            if n == difficulty:
                pygame.draw.line(self.screen, ACCENT, (r.left, r.bottom + 4), (r.right, r.bottom + 4), 3)
            x += w + 60
        self.text(self.font_small, "< left / right >", DIM, center=(WIDTH / 2, 360))
        if best:
            self.text(self.font, f"best: {best:,}", GOLD, center=(WIDTH / 2, 395))

        if int(t * 2) % 2 == 0:
            self.text(self.font_mid, "press SPACE to play", TEXT, center=(WIDTH / 2, 540))
        self.text(
            self.font_small,
            "up/down or W/S to move   P pause   M mute   Esc quit",
            DIM,
            center=(WIDTH / 2, HEIGHT - 24),
        )

    def draw_message(self, title: str, subtitle: str = "") -> None:
        self.text(self.font_big, title, TEXT, center=(WIDTH / 2, HEIGHT / 2 - 30))
        if subtitle:
            self.text(self.font, subtitle, DIM, center=(WIDTH / 2, HEIGHT / 2 + 30))

    def draw_results(self, world: World, rank: int | None, best: int) -> None:
        self.dim(190)
        title = "SONG CLEARED" if world.cleared else "GAME OVER"
        color = ACCENT if world.cleared else DANGER
        self.text(self.font_big, title, color, center=(WIDTH / 2, 120))
        self.text(self.font_big, f"{world.score:,}", TEXT, center=(WIDTH / 2, 210))
        if rank == 1:
            self.text(self.font_mid, "NEW HIGH SCORE!", GOLD, center=(WIDTH / 2, 270))
        elif rank:
            self.text(self.font, f"#{rank} on the board   (best {best:,})", GOLD, center=(WIDTH / 2, 270))
        else:
            self.text(self.font, f"best {best:,}", DIM, center=(WIDTH / 2, 270))

        rows = [
            ("caught", f"{world.caught}  ({world.perfect} perfect)"),
            ("missed", f"{world.missed}"),
            ("accuracy", f"{world.accuracy * 100:.0f}%"),
            ("hazards hit", f"{world.hits}"),
            ("best combo", f"{world.best_streak}"),
            ("song", f"{world.progress * 100:.0f}%"),
        ]
        y = 310
        for label, value in rows:
            self.text(self.font, label, DIM, topright=(WIDTH / 2 - 16, y))
            self.text(self.font, value, TEXT, topleft=(WIDTH / 2 + 16, y))
            y += 32
        self.text(self.font, "R retry    Enter menu    Esc quit", TEXT, center=(WIDTH / 2, HEIGHT - 40))
