import pygame
import sounddevice as sd
import soundfile as sf
import time
import threading
import random

def run_game(y, sr, wav_path, pitch_track, min_pitch, max_pitch):
    def pitch_to_y(pitch):
        if pitch is None:
            return 300
        pitch_range = max_pitch - min_pitch
        return 600 - int((pitch - min_pitch) / pitch_range * 600)

    def play_audio():
        data, fs = sf.read(wav_path, dtype='float32')
        sd.play(data, fs)

    def handle_input():
        nonlocal player_y, running
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP]:
            player_y -= PLAYER_SPEED
        if keys[pygame.K_DOWN]:
            player_y += PLAYER_SPEED
        player_y = max(PADDLE_HEIGHT // 2, min(600 - PADDLE_HEIGHT // 2, player_y))
        paddle_rect.y = player_y - PADDLE_HEIGHT // 2

    def update_dots():
        nonlocal score, last_collision_time, last_spawn_time, spawn_interval, dot_speed_multiplier

        # Gradually make game harder
        time_elapsed = current_time - start_time
        spawn_interval = max(MIN_SPAWN_INTERVAL, INITIAL_SPAWN_INTERVAL - time_elapsed * 0.01)  # Faster spawning
        dot_speed_multiplier = 1.0 + time_elapsed * 0.03  # Faster dots

        # Spawn new dot if interval passed
        if (current_time - last_spawn_time) > spawn_interval and 0 <= audio_index < len(pitch_track):
            y_pos = pitch_to_y(pitch_track[audio_index])
            dx = random.uniform(4.5, 6.5) * dot_speed_multiplier
            dy = random.uniform(-2.5, 2.5) * dot_speed_multiplier
            dots.append([0, y_pos, dx, dy, False])  # x, y, dx, dy, scored
            last_spawn_time = current_time

        scoring_disabled = (current_time - last_collision_time) < SCORING_DISABLE_DURATION

        for dot in dots[:]:
            dot[0] += dot[2]  # dx
            dot[1] += dot[3]  # dy
            x, y, dx, dy, scored = dot

            collided = (
                paddle_rect.left - 10 < x < paddle_rect.right + 10
                and abs(y - player_y) < PADDLE_HEIGHT // 1.5
            )
            if collided:
                last_collision_time = current_time

            if x > paddle_rect.right + 10 and not scored:
                if not scoring_disabled:
                    score += 1
                dot[4] = True

            if x > 810 or y < -10 or y > 610:
                dots.remove(dot)

    def draw():
        screen.fill((0, 0, 0))
        for x, y, dx, dy, scored in dots:
            color = (255, 0, 0) if (paddle_rect.left - 10 < x < paddle_rect.right + 10 and abs(y - player_y) < PADDLE_HEIGHT // 1.5) else (255, 100, 100)
            pygame.draw.circle(screen, color, (int(x), int(y)), 10)

        pygame.draw.rect(screen, (100, 255, 100), paddle_rect)
        score_text = font.render(f"Score: {score}", True, (255, 255, 255))
        screen.blit(score_text, (10, 10))
        pygame.display.flip()

    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("\U0001F3AE Pitch Dodge")
    clock = pygame.time.Clock()

    PADDLE_X = 700
    PADDLE_WIDTH = 20
    PADDLE_HEIGHT = 60
    PLAYER_SPEED = 6
    SCORING_DISABLE_DURATION = 0.05

    INITIAL_SPAWN_INTERVAL = 0.5
    MIN_SPAWN_INTERVAL = 0.1

    dots = []
    player_y = 300
    paddle_rect = pygame.Rect(PADDLE_X, player_y - PADDLE_HEIGHT // 2, PADDLE_WIDTH, PADDLE_HEIGHT)
    score = 0
    last_collision_time = 0
    last_spawn_time = 0
    spawn_interval = INITIAL_SPAWN_INTERVAL
    dot_speed_multiplier = 1.0
    font = pygame.font.SysFont(None, 36)
    running = True

    threading.Thread(target=play_audio, daemon=True).start()
    start_time = time.time()

    print("Game started!")

    while running:
        elapsed = time.time() - start_time
        audio_index = int(elapsed * sr / 512)
        current_time = time.time()

        handle_input()
        update_dots()
        draw()

        clock.tick(60)

    pygame.quit()
    sd.stop()
    print("Done.")
