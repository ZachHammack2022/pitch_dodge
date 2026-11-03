"""Tiny synthesized sound effects, so the repo needs no extra sound files."""

from __future__ import annotations

import numpy as np
import pygame


def _tone(freqs, duration, volume, decay, noise=0.0):
    init = pygame.mixer.get_init()
    if not init:
        return None
    rate, _, channels = init
    t = np.arange(int(rate * duration)) / rate
    wave = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
    if noise:
        wave = wave * (1 - noise) + np.random.default_rng(0).uniform(-1, 1, len(t)) * noise
    env = np.exp(-t * decay) * np.minimum(1, t * 400)  # quick attack, exponential decay
    samples = (wave * env * volume * 32767).astype(np.int16)
    if channels > 1:
        samples = np.repeat(samples[:, None], channels, axis=1)
    return pygame.mixer.Sound(buffer=np.ascontiguousarray(samples).tobytes())


class Sfx:
    def __init__(self, enabled: bool):
        self.sounds = {}
        self.enabled = enabled
        if not enabled:
            return
        try:
            self.sounds = {
                "hit": _tone([110, 82], 0.35, 0.6, 9, noise=0.4),
                "near_miss": _tone([1320, 1760], 0.15, 0.25, 25),
                "level_up": _tone([660, 880, 1320], 0.4, 0.3, 7),
                "game_over": _tone([196, 147, 98], 1.0, 0.45, 3),
                "cleared": _tone([523, 659, 784, 1047], 1.0, 0.35, 3),
            }
        except (pygame.error, ValueError):
            self.sounds = {}

    def play(self, kind: str) -> None:
        if self.enabled and (s := self.sounds.get(kind)) is not None:
            s.play()
