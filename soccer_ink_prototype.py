import math
import random
from array import array

import pygame


WIDTH, HEIGHT = 1100, 650
FPS = 120

FIELD_MARGIN = 40
FIELD_CORNER_RADIUS = 92
GOAL_OPENING = 246
GOAL_DEPTH = 30
GOAL_LINE_X_LEFT = FIELD_MARGIN
GOAL_LINE_X_RIGHT = WIDTH - FIELD_MARGIN
GOAL_TOP = HEIGHT / 2 - GOAL_OPENING / 2
GOAL_BOTTOM = HEIGHT / 2 + GOAL_OPENING / 2
GOAL_CENTER_Y = HEIGHT * 0.5

BALL_RADIUS = 14
BALL_DAMPING = 0.995
BALL_MAX_SPEED = 1100

BOOST_PAD_THICKNESS = 8
BOOST_PAD_MIN_DRAG = 14
BOOST_PAD_MAX_LENGTH = BALL_RADIUS * 2 * 5
BOOST_IMPULSE_MIN = 200
BOOST_IMPULSE_MAX = 760
BOOST_COOLDOWN = 0.22

BARRIER_THICKNESS = 6
BARRIER_SEGMENT_STEP = 8
BARRIER_LIFETIME = 2.0
MAX_INK_LENGTH = GOAL_OPENING * 0.34

KICKOFF_COUNTDOWN = 3.0
GOAL_SHIELD_DURATION = 3.0
SHIELD_RADIUS = 120
SHIELD_INSET_X = 28

# Rounded boost-block zone in front of each goal.
# Height is 1.5x goal width (opening), with rounded corners and straight front line.
BOOST_BLOCK_HEIGHT = int(GOAL_OPENING * 1.5)
BOOST_BLOCK_DEPTH = int(GOAL_OPENING * 0.75)
BOOST_BLOCK_RADIUS = min(BOOST_BLOCK_DEPTH // 2, BOOST_BLOCK_HEIGHT // 2 - 4)
BOOST_ZONE_MULTIPLIER = 0.30
STALL_SPEED_THRESHOLD = 20.0
STALL_TIME_TO_NUDGE = 0.65
STALL_NUDGE_IMPULSE = 170.0

BG_COLOR = (8, 13, 22)
PITCH_COLOR = (18, 86, 74)
PITCH_INNER_COLOR = (14, 66, 58)
LINE_COLOR = (200, 245, 240)
GOAL_COLOR = (90, 220, 255)
BALL_COLOR = (245, 250, 255)
BALL_STROKE = (20, 32, 40)
BOOST_COLOR = (66, 202, 255)
BARRIER_COLOR = (255, 110, 128)
SHIELD_COLOR = (255, 165, 70, 132)
BLOCK_ZONE_FILL = (255, 55, 55, 120)
BLOCK_ZONE_EDGE = (255, 95, 95, 210)
PANEL_BG = (10, 24, 35, 185)
PANEL_EDGE = (84, 186, 220, 130)
TEXT_COLOR = (228, 244, 255)
MUTED_TEXT = (150, 190, 210)


def clamp(value, low, high):
    return max(low, min(high, value))


def vec_len(v):
    return math.hypot(v[0], v[1])


def normalize(v):
    length = vec_len(v)
    if length == 0:
        return pygame.Vector2()
    return pygame.Vector2(v[0] / length, v[1] / length)


def distance_point_to_segment(point, a, b):
    ap = point - a
    ab = b - a
    ab_len_sq = ab.dot(ab)
    if ab_len_sq == 0:
        return ap.length(), a, 0.0
    t = clamp(ap.dot(ab) / ab_len_sq, 0.0, 1.0)
    closest = a + ab * t
    return (point - closest).length(), closest, t


def segment_normal(a, b):
    d = b - a
    n = pygame.Vector2(-d.y, d.x)
    if n.length_squared() == 0:
        return pygame.Vector2(0, -1)
    return n.normalize()


def clamp_drag_line(a, b, max_len):
    delta = b - a
    dist = delta.length()
    if dist <= max_len or dist <= 1e-6:
        return pygame.Vector2(b)
    return pygame.Vector2(a + delta * (max_len / dist))


def draw_panel(surface, rect, radius=14):
    panel = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(panel, PANEL_BG, panel.get_rect(), border_radius=radius)
    pygame.draw.rect(panel, PANEL_EDGE, panel.get_rect(), width=2, border_radius=radius)
    surface.blit(panel, rect.topleft)


def point_in_rounded_rect(point, rect, radius):
    if not rect.collidepoint(point.x, point.y):
        return False

    cx = clamp(point.x, rect.left + radius, rect.right - radius)
    cy = clamp(point.y, rect.top + radius, rect.bottom - radius)
    dx = point.x - cx
    dy = point.y - cy
    return dx * dx + dy * dy <= radius * radius


class BarrierSegment:
    def __init__(self, a, b, created):
        self.a = pygame.Vector2(a)
        self.b = pygame.Vector2(b)
        self.created = created
        self.length = (self.b - self.a).length()

    def age(self, now):
        return now - self.created

    def alive(self, now):
        return self.age(now) < BARRIER_LIFETIME

    def alpha(self, now):
        return clamp(1.0 - self.age(now) / BARRIER_LIFETIME, 0.0, 1.0)


class BoostPad:
    def __init__(self, a, b):
        self.a = pygame.Vector2(a)
        self.b = clamp_drag_line(self.a, pygame.Vector2(b), BOOST_PAD_MAX_LENGTH)
        drag_dir = self.b - self.a
        self.length = drag_dir.length()
        self.dir = normalize((self.a - self.b))
        self.valid = self.length >= BOOST_PAD_MIN_DRAG and self.dir.length_squared() > 0


class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Ink Soccer Prototype")
        self.clock = pygame.time.Clock()

        self.fonts_ok = True
        try:
            pygame.font.init()
            self.font_big = pygame.font.SysFont("Avenir Next", 52, bold=True)
            self.font_small = pygame.font.SysFont("Avenir Next", 18)
            self.font_kickoff = pygame.font.SysFont("Avenir Next", 34, bold=True)
        except Exception:
            self.fonts_ok = False

        self.sound_ok = False
        self.snd_boost = None
        self.snd_goal = None
        self.snd_shield = None
        self.snd_countdown = None
        self.last_shield_sound_time = -10.0
        self.last_countdown_value = None
        self.setup_audio()

        self.ball_pos = pygame.Vector2(WIDTH * 0.5, HEIGHT * 0.5)
        self.ball_vel = pygame.Vector2()

        self.left_score = 0
        self.right_score = 0

        self.boost_pad = None
        self.last_boost_time = -10.0

        self.barriers = []
        self.ink_used = 0.0

        self.left_drag_start = None
        self.left_drag_current = None
        self.right_drawing = False
        self.right_last_point = None

        self.kickoff_side = random.choice(["left", "right"])
        self.kickoff_phase = "countdown"  # countdown -> waiting_touch -> live
        self.kickoff_countdown_end = 0.0
        self.shield_end_time = 0.0
        self.user_side = "left"
        self.player_toggle_rect = pygame.Rect(18, HEIGHT - 54, 236, 36)
        self.zone_stall_timer = 0.0

        zone_top = int(GOAL_CENTER_Y - BOOST_BLOCK_HEIGHT * 0.5)
        self.left_block_zone = pygame.Rect(
            int(GOAL_LINE_X_LEFT - BOOST_BLOCK_DEPTH * 0.5),
            zone_top,
            int(BOOST_BLOCK_DEPTH),
            int(BOOST_BLOCK_HEIGHT),
        )
        self.right_block_zone = pygame.Rect(
            int(GOAL_LINE_X_RIGHT - BOOST_BLOCK_DEPTH * 0.5),
            zone_top,
            int(BOOST_BLOCK_DEPTH),
            int(BOOST_BLOCK_HEIGHT),
        )

        self.start_kickoff(0.0, self.kickoff_side)

    def setup_audio(self):
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
            self.sound_ok = True
            self.snd_boost = self.make_tone(560, 0.07, 0.25)
            self.snd_goal = self.make_tone(220, 0.24, 0.30)
            self.snd_shield = self.make_tone(760, 0.05, 0.22)
            self.snd_countdown = self.make_tone(680, 0.05, 0.16)
        except Exception:
            self.sound_ok = False

    def make_tone(self, freq_hz, seconds, volume):
        if not self.sound_ok:
            return None
        sample_rate = 44100
        total = int(sample_rate * seconds)
        buf = array("h")
        for i in range(total):
            t = i / sample_rate
            env = 1.0 - (i / max(1, total - 1))
            sample = math.sin(2.0 * math.pi * freq_hz * t) * env
            buf.append(int(32767 * volume * sample))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def play_sound(self, snd):
        if self.sound_ok and snd is not None:
            snd.play()

    def clear_drawables(self):
        self.boost_pad = None
        self.barriers.clear()
        self.ink_used = 0.0
        self.left_drag_start = None
        self.left_drag_current = None
        self.right_drawing = False
        self.right_last_point = None

    def half_center_x(self, side):
        return WIDTH * 0.25 if side == "left" else WIDTH * 0.75

    def point_in_side(self, p, side):
        mid = WIDTH * 0.5
        return p.x <= mid if side == "left" else p.x >= mid

    def kickoff_controls_locked(self):
        return self.kickoff_phase == "countdown"

    def kickoff_side_restricted(self):
        return self.kickoff_phase == "waiting_touch"

    def user_can_interact_at(self, p):
        if self.kickoff_controls_locked():
            return False
        if self.kickoff_side_restricted():
            if self.user_side != self.kickoff_side:
                return False
            return self.point_in_side(p, self.kickoff_side)
        return True

    def start_kickoff(self, now, conceding_side):
        self.kickoff_side = conceding_side
        self.kickoff_phase = "countdown"
        self.kickoff_countdown_end = now + KICKOFF_COUNTDOWN
        self.shield_end_time = 0.0
        self.last_countdown_value = None
        self.ball_pos.update(self.half_center_x(conceding_side), HEIGHT * 0.5)
        self.ball_vel.update(0, 0)

    def remove_expired_barriers(self, now):
        if not self.barriers:
            return
        alive = []
        used = 0.0
        for seg in self.barriers:
            if seg.alive(now):
                alive.append(seg)
                used += seg.length
        self.barriers = alive
        self.ink_used = used

    def add_barrier_stroke(self, p0, p1, now):
        delta = p1 - p0
        dist = delta.length()
        if dist < 1e-5:
            return

        direction = delta / dist
        steps = max(1, int(dist // BARRIER_SEGMENT_STEP))

        prev = pygame.Vector2(p0)
        for i in range(1, steps + 1):
            t = i / steps
            cur = p0 + delta * t
            piece_len = (cur - prev).length()
            if self.ink_used + piece_len > MAX_INK_LENGTH:
                break
            seg = BarrierSegment(prev, cur, now)
            self.barriers.append(seg)
            self.ink_used += seg.length
            prev = cur

        if prev != p0:
            self.right_last_point = pygame.Vector2(prev)
        else:
            self.right_last_point = pygame.Vector2(p0 + direction * min(dist, 1.0))

    def point_in_boost_block_zone(self, p):
        return point_in_rounded_rect(p, self.left_block_zone, BOOST_BLOCK_RADIUS) or point_in_rounded_rect(
            p, self.right_block_zone, BOOST_BLOCK_RADIUS
        )

    def boost_allowed(self, candidate):
        if candidate is None or not candidate.valid:
            return False

        if self.kickoff_side_restricted() and self.user_side != self.kickoff_side:
            return False

        samples = 11
        for i in range(samples + 1):
            t = i / samples
            p = candidate.a.lerp(candidate.b, t)
            if self.kickoff_side_restricted() and not self.point_in_side(p, self.kickoff_side):
                return False
        return True

    def apply_boost_if_crossed(self, now):
        if self.boost_pad is None or not self.boost_pad.valid:
            return
        if now - self.last_boost_time < BOOST_COOLDOWN:
            return

        d, _, _ = distance_point_to_segment(self.ball_pos, self.boost_pad.a, self.boost_pad.b)
        if d <= BALL_RADIUS + BOOST_PAD_THICKNESS:
            ratio = clamp(self.boost_pad.length / BOOST_PAD_MAX_LENGTH, 0.0, 1.0)
            impulse = BOOST_IMPULSE_MIN + ratio * (BOOST_IMPULSE_MAX - BOOST_IMPULSE_MIN)
            if self.point_in_boost_block_zone(self.ball_pos):
                impulse *= BOOST_ZONE_MULTIPLIER
            self.ball_vel += self.boost_pad.dir * impulse
            speed = self.ball_vel.length()
            if speed > BALL_MAX_SPEED:
                self.ball_vel.scale_to_length(BALL_MAX_SPEED)
            self.last_boost_time = now
            self.play_sound(self.snd_boost)

            if self.kickoff_phase == "waiting_touch":
                self.kickoff_phase = "live"
                self.shield_end_time = now + GOAL_SHIELD_DURATION

    def collide_ball_with_segment(self, seg):
        d, closest, _ = distance_point_to_segment(self.ball_pos, seg.a, seg.b)
        if d >= BALL_RADIUS + BARRIER_THICKNESS * 0.5:
            return

        n = self.ball_pos - closest
        if n.length_squared() == 0:
            n = segment_normal(seg.a, seg.b)
        else:
            n = n.normalize()

        penetration = BALL_RADIUS + BARRIER_THICKNESS * 0.5 - d
        self.ball_pos += n * penetration

        vn = self.ball_vel.dot(n)
        if vn < 0:
            self.ball_vel -= (1.95 * vn) * n

    def reflect_off_normal(self, normal):
        vn = self.ball_vel.dot(normal)
        if vn > 0:
            self.ball_vel -= (1.95 * vn) * normal

    def shield_active(self, now):
        return now < self.shield_end_time

    def collide_ball_with_goal_shields(self, now):
        if not self.shield_active(now):
            return

        centers = [
            pygame.Vector2(GOAL_LINE_X_LEFT + SHIELD_INSET_X, HEIGHT * 0.5),
            pygame.Vector2(GOAL_LINE_X_RIGHT - SHIELD_INSET_X, HEIGHT * 0.5),
        ]
        block_radius = SHIELD_RADIUS + BALL_RADIUS

        for center in centers:
            rel = self.ball_pos - center
            dist = rel.length()
            if dist <= 1e-6:
                continue
            if dist < block_radius:
                n = rel / dist
                self.ball_pos = center + n * block_radius
                vn = self.ball_vel.dot(n)
                if vn < 0:
                    self.ball_vel -= (2.25 * vn) * n
                    if now - self.last_shield_sound_time > 0.08:
                        self.play_sound(self.snd_shield)
                        self.last_shield_sound_time = now

    def apply_zone_stall_nudge(self, dt):
        if self.kickoff_phase != "live":
            self.zone_stall_timer = 0.0
            return

        speed = self.ball_vel.length()
        in_zone = self.point_in_boost_block_zone(self.ball_pos)
        if in_zone and speed < STALL_SPEED_THRESHOLD:
            self.zone_stall_timer += dt
            if self.zone_stall_timer >= STALL_TIME_TO_NUDGE:
                if self.ball_pos.x <= WIDTH * 0.5:
                    center = pygame.Vector2(GOAL_LINE_X_LEFT, GOAL_CENTER_Y)
                    fallback = pygame.Vector2(1, 0)
                else:
                    center = pygame.Vector2(GOAL_LINE_X_RIGHT, GOAL_CENTER_Y)
                    fallback = pygame.Vector2(-1, 0)

                n = self.ball_pos - center
                if n.length_squared() == 0:
                    n = fallback
                else:
                    n = n.normalize()

                self.ball_vel += n * STALL_NUDGE_IMPULSE
                if self.ball_vel.length() > BALL_MAX_SPEED:
                    self.ball_vel.scale_to_length(BALL_MAX_SPEED)
                self.zone_stall_timer = 0.0
                self.play_sound(self.snd_shield)
        else:
            self.zone_stall_timer = 0.0

    def on_goal(self, scorer_right, now):
        if scorer_right:
            self.right_score += 1
            conceding = "left"
        else:
            self.left_score += 1
            conceding = "right"

        self.play_sound(self.snd_goal)
        self.clear_drawables()
        self.start_kickoff(now, conceding)

    def handle_rounded_field_collisions_and_goals(self, now):
        left = FIELD_MARGIN
        right = WIDTH - FIELD_MARGIN
        top = FIELD_MARGIN
        bottom = HEIGHT - FIELD_MARGIN
        corner = FIELD_CORNER_RADIUS

        in_goal_window = GOAL_TOP <= self.ball_pos.y <= GOAL_BOTTOM

        if self.ball_pos.x - BALL_RADIUS < GOAL_LINE_X_LEFT and in_goal_window:
            self.on_goal(scorer_right=True, now=now)
            return True

        if self.ball_pos.x + BALL_RADIUS > GOAL_LINE_X_RIGHT and in_goal_window:
            self.on_goal(scorer_right=False, now=now)
            return True

        if left + corner <= self.ball_pos.x <= right - corner and self.ball_pos.y - BALL_RADIUS < top:
            self.ball_pos.y = top + BALL_RADIUS
            self.reflect_off_normal(pygame.Vector2(0, -1))

        if left + corner <= self.ball_pos.x <= right - corner and self.ball_pos.y + BALL_RADIUS > bottom:
            self.ball_pos.y = bottom - BALL_RADIUS
            self.reflect_off_normal(pygame.Vector2(0, 1))

        if top + corner <= self.ball_pos.y <= GOAL_TOP and self.ball_pos.x - BALL_RADIUS < left:
            self.ball_pos.x = left + BALL_RADIUS
            self.reflect_off_normal(pygame.Vector2(-1, 0))

        if GOAL_BOTTOM <= self.ball_pos.y <= bottom - corner and self.ball_pos.x - BALL_RADIUS < left:
            self.ball_pos.x = left + BALL_RADIUS
            self.reflect_off_normal(pygame.Vector2(-1, 0))

        if top + corner <= self.ball_pos.y <= GOAL_TOP and self.ball_pos.x + BALL_RADIUS > right:
            self.ball_pos.x = right - BALL_RADIUS
            self.reflect_off_normal(pygame.Vector2(1, 0))

        if GOAL_BOTTOM <= self.ball_pos.y <= bottom - corner and self.ball_pos.x + BALL_RADIUS > right:
            self.ball_pos.x = right - BALL_RADIUS
            self.reflect_off_normal(pygame.Vector2(1, 0))

        corners = [
            (pygame.Vector2(left + corner, top + corner), lambda p: p.x < left + corner and p.y < top + corner),
            (pygame.Vector2(right - corner, top + corner), lambda p: p.x > right - corner and p.y < top + corner),
            (pygame.Vector2(left + corner, bottom - corner), lambda p: p.x < left + corner and p.y > bottom - corner),
            (pygame.Vector2(right - corner, bottom - corner), lambda p: p.x > right - corner and p.y > bottom - corner),
        ]

        allowed = corner - BALL_RADIUS
        for center, in_zone in corners:
            if not in_zone(self.ball_pos):
                continue
            rel = self.ball_pos - center
            dist = rel.length()
            if dist <= 1e-6:
                continue
            if dist > allowed:
                n = rel / dist
                self.ball_pos = center + n * allowed
                self.reflect_off_normal(n)

        return False

    def update(self, dt, now):
        self.remove_expired_barriers(now)

        if self.kickoff_phase == "countdown":
            self.ball_pos.update(self.half_center_x(self.kickoff_side), HEIGHT * 0.5)
            self.ball_vel.update(0, 0)
            remain = max(0.0, self.kickoff_countdown_end - now)
            value = int(math.ceil(remain))
            if value != self.last_countdown_value and value > 0:
                self.play_sound(self.snd_countdown)
            self.last_countdown_value = value
            if now >= self.kickoff_countdown_end:
                self.kickoff_phase = "waiting_touch"
            return

        if self.kickoff_phase == "waiting_touch":
            self.ball_pos.update(self.half_center_x(self.kickoff_side), HEIGHT * 0.5)
            self.ball_vel.update(0, 0)
            self.apply_boost_if_crossed(now)
            return

        self.ball_pos += self.ball_vel * dt
        self.ball_vel *= BALL_DAMPING
        self.apply_zone_stall_nudge(dt)

        speed = self.ball_vel.length()
        if speed > BALL_MAX_SPEED:
            self.ball_vel.scale_to_length(BALL_MAX_SPEED)

        self.collide_ball_with_goal_shields(now)

        scored = self.handle_rounded_field_collisions_and_goals(now)
        if scored:
            return

        self.apply_boost_if_crossed(now)

        for seg in self.barriers:
            self.collide_ball_with_segment(seg)

    def draw_background(self):
        self.screen.fill(BG_COLOR)
        for y in range(0, HEIGHT, 2):
            mix = y / HEIGHT
            c = (
                int(8 + 8 * mix),
                int(13 + 22 * mix),
                int(22 + 26 * mix),
            )
            pygame.draw.line(self.screen, c, (0, y), (WIDTH, y))

    def draw_field(self):
        pitch = pygame.Rect(FIELD_MARGIN, FIELD_MARGIN, WIDTH - 2 * FIELD_MARGIN, HEIGHT - 2 * FIELD_MARGIN)
        pygame.draw.rect(self.screen, PITCH_COLOR, pitch, border_radius=FIELD_CORNER_RADIUS)

        inner = pitch.inflate(-18, -18)
        pygame.draw.rect(self.screen, PITCH_INNER_COLOR, inner, width=2, border_radius=max(8, FIELD_CORNER_RADIUS - 10))
        pygame.draw.rect(self.screen, LINE_COLOR, pitch, width=3, border_radius=FIELD_CORNER_RADIUS)

        pygame.draw.line(
            self.screen,
            (150, 225, 215),
            (WIDTH // 2, FIELD_MARGIN + 12),
            (WIDTH // 2, HEIGHT - FIELD_MARGIN - 12),
            2,
        )
        pygame.draw.circle(self.screen, (150, 225, 215), (WIDTH // 2, HEIGHT // 2), 70, width=2)

        left_goal_box = pygame.Rect(FIELD_MARGIN - GOAL_DEPTH, GOAL_TOP, GOAL_DEPTH, GOAL_OPENING)
        right_goal_box = pygame.Rect(GOAL_LINE_X_RIGHT, GOAL_TOP, GOAL_DEPTH, GOAL_OPENING)
        pygame.draw.rect(self.screen, GOAL_COLOR, left_goal_box, width=3, border_radius=5)
        pygame.draw.rect(self.screen, GOAL_COLOR, right_goal_box, width=3, border_radius=5)

        pygame.draw.line(self.screen, GOAL_COLOR, (GOAL_LINE_X_LEFT, GOAL_TOP), (GOAL_LINE_X_LEFT, GOAL_BOTTOM), 4)
        pygame.draw.line(self.screen, GOAL_COLOR, (GOAL_LINE_X_RIGHT, GOAL_TOP), (GOAL_LINE_X_RIGHT, GOAL_BOTTOM), 4)

    def draw_boost_block_zones(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        pitch_rect = pygame.Rect(FIELD_MARGIN, FIELD_MARGIN, WIDTH - 2 * FIELD_MARGIN, HEIGHT - 2 * FIELD_MARGIN)
        overlay.set_clip(pitch_rect)
        pygame.draw.rect(overlay, BLOCK_ZONE_FILL, self.left_block_zone, border_radius=BOOST_BLOCK_RADIUS)
        pygame.draw.rect(overlay, BLOCK_ZONE_FILL, self.right_block_zone, border_radius=BOOST_BLOCK_RADIUS)
        pygame.draw.rect(overlay, BLOCK_ZONE_EDGE, self.left_block_zone, width=3, border_radius=BOOST_BLOCK_RADIUS)
        pygame.draw.rect(overlay, BLOCK_ZONE_EDGE, self.right_block_zone, width=3, border_radius=BOOST_BLOCK_RADIUS)
        overlay.set_clip(None)
        self.screen.blit(overlay, (0, 0))

    def draw_shields(self, now):
        if not self.shield_active(now):
            return
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        pygame.draw.circle(overlay, SHIELD_COLOR, (int(GOAL_LINE_X_LEFT + SHIELD_INSET_X), HEIGHT // 2), SHIELD_RADIUS)
        pygame.draw.circle(overlay, SHIELD_COLOR, (int(GOAL_LINE_X_RIGHT - SHIELD_INSET_X), HEIGHT // 2), SHIELD_RADIUS)
        pygame.draw.circle(overlay, (255, 190, 115, 210), (int(GOAL_LINE_X_LEFT + SHIELD_INSET_X), HEIGHT // 2), SHIELD_RADIUS, 4)
        pygame.draw.circle(overlay, (255, 190, 115, 210), (int(GOAL_LINE_X_RIGHT - SHIELD_INSET_X), HEIGHT // 2), SHIELD_RADIUS, 4)
        self.screen.blit(overlay, (0, 0))

    def draw_boost_pad(self):
        if self.boost_pad is not None and self.boost_pad.valid:
            a = (int(self.boost_pad.a.x), int(self.boost_pad.a.y))
            b = (int(self.boost_pad.b.x), int(self.boost_pad.b.y))
            pygame.draw.line(self.screen, BOOST_COLOR, a, b, BOOST_PAD_THICKNESS)

            pad_vec = self.boost_pad.b - self.boost_pad.a
            pad_len = pad_vec.length()
            if pad_len > 1e-5:
                tangent = pad_vec / pad_len
                normal = pygame.Vector2(-tangent.y, tangent.x)
                arrow_dir = self.boost_pad.dir
                for i in range(1, 5):
                    t = i / 5.0
                    p = self.boost_pad.a.lerp(self.boost_pad.b, t)
                    head = p + arrow_dir * 16
                    wing_l = p + normal * 5
                    wing_r = p - normal * 5
                    pygame.draw.line(self.screen, (190, 240, 255), wing_l, head, 2)
                    pygame.draw.line(self.screen, (190, 240, 255), wing_r, head, 2)

        if self.left_drag_start is not None and self.left_drag_current is not None:
            end = clamp_drag_line(self.left_drag_start, self.left_drag_current, BOOST_PAD_MAX_LENGTH)
            pygame.draw.line(self.screen, (120, 160, 190), self.left_drag_start, end, 2)

    def draw_barriers(self, now):
        for seg in self.barriers:
            alpha = seg.alpha(now)
            color = (
                int(BARRIER_COLOR[0] * alpha),
                int(BARRIER_COLOR[1] * alpha),
                int(BARRIER_COLOR[2] * alpha),
            )
            pygame.draw.line(self.screen, color, seg.a, seg.b, BARRIER_THICKNESS)

        if self.right_drawing and self.right_last_point is not None:
            m = pygame.Vector2(pygame.mouse.get_pos())
            pygame.draw.line(self.screen, (255, 160, 170), self.right_last_point, m, 2)

    def draw_ball(self):
        shadow_pos = self.ball_pos + pygame.Vector2(2.4, 2.8)
        pygame.draw.circle(self.screen, (5, 10, 12), shadow_pos, BALL_RADIUS + 1)
        pygame.draw.circle(self.screen, BALL_COLOR, self.ball_pos, BALL_RADIUS)
        pygame.draw.circle(self.screen, BALL_STROKE, self.ball_pos, BALL_RADIUS, width=2)

    def draw_ui(self, now):
        top_panel = pygame.Rect(WIDTH // 2 - 200, 10, 400, 78)
        ink_panel = pygame.Rect(WIDTH - 290, 12, 270, 82)
        draw_panel(self.screen, top_panel)
        draw_panel(self.screen, ink_panel)
        draw_panel(self.screen, self.player_toggle_rect, radius=10)

        if self.fonts_ok:
            player_label = "Player 1 (Left)" if self.user_side == "left" else "Player 2 (Right)"
            ptxt = self.font_small.render(f"Control: {player_label}", True, TEXT_COLOR)
            prect = ptxt.get_rect(center=self.player_toggle_rect.center)
            self.screen.blit(ptxt, prect)

            score_txt = self.font_big.render(f"{self.left_score}  :  {self.right_score}", True, TEXT_COLOR)
            score_rect = score_txt.get_rect(center=(top_panel.centerx, top_panel.centery + 2))
            self.screen.blit(score_txt, score_rect)

            label = self.font_small.render("INK", True, MUTED_TEXT)
            self.screen.blit(label, (ink_panel.x + 16, ink_panel.y + 10))

        bar_x = ink_panel.x + 16
        bar_y = ink_panel.y + 38
        bar_w = ink_panel.width - 32
        bar_h = 22
        pygame.draw.rect(self.screen, (35, 52, 66), (bar_x, bar_y, bar_w, bar_h), border_radius=8)
        remaining = clamp((MAX_INK_LENGTH - self.ink_used) / MAX_INK_LENGTH, 0.0, 1.0)
        fill_w = int((bar_w - 4) * remaining)
        pygame.draw.rect(self.screen, BARRIER_COLOR, (bar_x + 2, bar_y + 2, fill_w, bar_h - 4), border_radius=6)
        pygame.draw.rect(self.screen, (160, 210, 230), (bar_x, bar_y, bar_w, bar_h), width=2, border_radius=8)

        if self.fonts_ok:
            pct = self.font_small.render(f"{int(remaining * 100)}%", True, TEXT_COLOR)
            self.screen.blit(pct, (bar_x + bar_w - pct.get_width(), bar_y + bar_h + 6))

            hint = self.font_small.render("L-drag: boost  R-drag: wall  R: reset", True, MUTED_TEXT)
            hint_rect = hint.get_rect(center=(WIDTH // 2, HEIGHT - 20))
            self.screen.blit(hint, hint_rect)

            if self.kickoff_phase == "countdown":
                remain = max(0.0, self.kickoff_countdown_end - now)
                value = int(math.ceil(remain))
                txt = self.font_kickoff.render(str(max(1, value)), True, (160, 240, 255))
                rect = txt.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 140))
                self.screen.blit(txt, rect)
            elif self.kickoff_phase == "waiting_touch":
                txt = self.font_kickoff.render("GO", True, (160, 240, 255))
                rect = txt.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 140))
                self.screen.blit(txt, rect)

            if self.shield_active(now):
                sec = max(0.0, self.shield_end_time - now)
                s_txt = self.font_small.render(f"GOAL SHIELDS {sec:0.1f}s", True, (255, 190, 120))
                s_rect = s_txt.get_rect(center=(WIDTH // 2, 98))
                self.screen.blit(s_txt, s_rect)

    def handle_events(self, now):
        controls_locked = self.kickoff_controls_locked()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                self.left_score = 0
                self.right_score = 0
                self.clear_drawables()
                self.start_kickoff(now, random.choice(["left", "right"]))

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.player_toggle_rect.collidepoint(event.pos):
                self.user_side = "right" if self.user_side == "left" else "left"
                continue

            if controls_locked:
                continue

            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    p = pygame.Vector2(event.pos)
                    if not self.user_can_interact_at(p):
                        continue
                    self.left_drag_start = p
                    self.left_drag_current = p
                elif event.button == 3:
                    p = pygame.Vector2(event.pos)
                    if not self.user_can_interact_at(p):
                        continue
                    self.right_drawing = True
                    self.right_last_point = p

            if event.type == pygame.MOUSEMOTION:
                if self.left_drag_start is not None:
                    self.left_drag_current = pygame.Vector2(event.pos)

                if self.right_drawing and self.right_last_point is not None:
                    p0 = self.right_last_point
                    p1 = pygame.Vector2(event.pos)
                    if not self.user_can_interact_at(p0) or not self.user_can_interact_at(p1):
                        continue
                    self.add_barrier_stroke(p0, p1, now)

            if event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1 and self.left_drag_start is not None and self.left_drag_current is not None:
                    candidate = BoostPad(self.left_drag_start, self.left_drag_current)
                    self.boost_pad = candidate if self.boost_allowed(candidate) else None
                    self.left_drag_start = None
                    self.left_drag_current = None
                elif event.button == 3:
                    self.right_drawing = False
                    self.right_last_point = None

        return True

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            now = pygame.time.get_ticks() / 1000.0

            running = self.handle_events(now)
            if not running:
                break

            self.update(dt, now)

            self.draw_background()
            self.draw_field()
            self.draw_boost_block_zones()
            self.draw_shields(now)
            self.draw_boost_pad()
            self.draw_barriers(now)
            self.draw_ball()
            self.draw_ui(now)
            pygame.display.flip()

        pygame.quit()


if __name__ == "__main__":
    Game().run()
