"""Original articulated development input. No detector imports or held-out truth.

Parameters below are builder-chosen development settings, not independently frozen
schedules, expected answers, or licensed public fixtures. No automatic file writes.
"""
from dataclasses import dataclass, replace
from math import cos, pi, sin
from random import Random
from ..landmarks import FrameBatch, LANDMARK_NAMES, Landmark, SourceError, StreamValidator, finite
from ..windows import missing_between, nominal_slot

PERTURBATIONS = (
    "occlusion", "dropout", "jitter", "partial_rom", "pause", "speed_drift", "yaw",
    "left_right_swap", "frame_drop", "timestamp_gap", "second_person", "reentry", "camera_obstruction",
)
NEGATIVES = ("stand_talk", "walk", "sit_stand", "pickup", "wave", "exit_reenter")
DEVELOPMENT_SEEDS = range(1000, 1600)
# Three explicit development levels; changing these is not changing independent gold.
STRENGTHS = (0.25, 0.50, 0.75)

@dataclass(frozen=True)
class DevelopmentConfig:
    seed: int
    perturbation: str | None = None
    strength: int = 1
    negative: str | None = None
    fps: float = 30.0
    duration: float = 32.0
    width: int = 640
    height: int = 480

    def __post_init__(self) -> None:
        if type(self.seed) is not int or self.seed not in DEVELOPMENT_SEEDS:
            raise SourceError("development_seed_required")
        if self.perturbation is not None and self.perturbation not in PERTURBATIONS:
            raise SourceError("invalid_perturbation")
        if type(self.strength) is not int or self.strength not in (1, 2, 3):
            raise SourceError("invalid_strength")
        if self.negative is not None and self.negative not in NEGATIVES:
            raise SourceError("invalid_negative")
        if not finite(self.fps) or not 1 <= self.fps <= 120 or not finite(self.duration) or not 32 <= self.duration <= 59:
            raise SourceError("invalid_development_duration_rate")
        if type(self.width) is not int or type(self.height) is not int or not 0 < self.width <= 16384 or not 0 < self.height <= 16384:
            raise SourceError("invalid_dimensions")

@dataclass(frozen=True)
class DevelopmentBody:
    torso: float
    thigh: float
    shin: float
    shoulder_half: float
    hip_half: float
    yaw: float
    distance: float
    period: float
    excursion: float

    @classmethod
    def from_seed(cls, seed: int) -> "DevelopmentBody":
        if type(seed) is not int or seed not in DEVELOPMENT_SEEDS:
            raise SourceError("development_seed_required")
        rng = Random(seed)
        return cls(rng.uniform(.18,.22), rng.uniform(.14,.18), rng.uniform(.14,.18), rng.uniform(.07,.10), rng.uniform(.045,.065), rng.uniform(-.35,.35), rng.uniform(.85,1.05), rng.uniform(2.4,3.6), rng.uniform(.65,1.0))

def _cycle(t: float, body: DevelopmentBody) -> float:
    if t < 3 or t >= 30:
        return 0.0
    phase = ((t - 3) % body.period) / body.period
    # Explicit descent, bottom pause, ascent, standing pause.
    if phase < .35:
        return body.excursion * phase / .35
    if phase < .45:
        return body.excursion
    if phase < .80:
        return body.excursion * (.80 - phase) / .35
    return 0.0

def _body_pose(t: float, body: DevelopmentBody, mode: str | None, *, flex_override: float | None = None, yaw_delta: float = 0.0) -> tuple[Landmark, ...]:
    flex = _cycle(t, body) if flex_override is None else flex_override
    hip_x, hip_y = .5, .88 - body.thigh - body.shin + .11 * flex
    arm = 0.0
    if mode is not None:
        flex = 0.0
        hip_y = .88 - body.thigh - body.shin
        if mode == "walk":
            hip_x += .24 * sin((t - 3) * pi / 10) if t >= 3 else 0
        elif mode == "sit_stand" and 8 <= t < 18:
            flex, hip_y = .9, hip_y + .11
        elif mode == "pickup" and 8 <= t < 13:
            flex = sin((t - 8) * pi / 5)
            hip_y += .05 * flex
        elif mode == "wave" and t >= 3:
            arm = .10 * sin(t * 3)
    # Forward kinematics preserves each person's thigh/shin segment lengths.
    phi = .9 * flex
    knee_y = .88 - body.shin * cos(phi)
    hip_y = knee_y - body.thigh * cos(phi)
    hip_shift = (body.shin - body.thigh) * sin(phi)
    points: dict[str, tuple[float, float, float]] = {}
    for side, sign in (("left", -1), ("right", 1)):
        ax = hip_x + sign * body.hip_half
        hx = ax + hip_shift
        points[side + "_hip"] = (hx, hip_y, 0)
        points[side + "_knee"] = (ax + body.shin * sin(phi), knee_y, 0)
        points[side + "_ankle"] = (ax, .88, 0)
        points[side + "_heel"] = (hx - .015, .89, 0)
        points[side + "_foot_index"] = (hx + .045, .90, 0)
        sx, sy = hip_x + hip_shift + sign * body.shoulder_half, hip_y - body.torso
        if mode == "pickup":
            sx += .10 * flex
            sy += .08 * flex
        points[side + "_shoulder"] = (sx, sy, 0)
        points[side + "_elbow"] = (sx + sign * .045, sy + .09 + arm, 0)
        wx, wy = sx + sign * .06, sy + .18 + 2 * arm
        points[side + "_wrist"] = (wx, wy, 0)
        for finger, dx in (("pinky", -.01), ("index", .01), ("thumb", 0)):
            points[side + "_" + finger] = (wx + dx, wy + .025, 0)
    head_y = hip_y - body.torso - .06
    points["nose"] = (hip_x + hip_shift, head_y, -.015)
    for name in LANDMARK_NAMES[:11]:
        if name == "nose":
            continue
        sign = -1 if name.startswith("left") or name == "mouth_left" else 1
        points[name] = (hip_x + hip_shift + sign * .018, head_y + (.02 if name.startswith("mouth") else -.012), 0)
    yaw = body.yaw + yaw_delta
    output = []
    for name in LANDMARK_NAMES:
        x, y, z = points[name]
        # Orthographic yaw plus camera-distance projection; no physical accuracy claim.
        xr = (x - .5) * cos(yaw) + z * sin(yaw)
        zr = -(x - .5) * sin(yaw) + z * cos(yaw)
        output.append(Landmark(name, .5 + xr * body.distance, .5 + (y - .5) * body.distance, zr * body.distance, 1.0, 1.0))
    return tuple(output)

class SyntheticSource:
    """One configured development stream. Seed space is strictly1000..1599.

    read() has no external effects. No public600-window corpus is generated on
    import/construction, and no held-out seed, schedule or expected list is exposed.
    """
    def __init__(self, config: DevelopmentConfig):
        self.config = config
        self._body = DevelopmentBody.from_seed(config.seed)
        self._rng = Random(config.seed + 100000)
        self._index = 0
        self._previous: float | None = None
        self._validator = StreamValidator()
        self._closed = False

    def read(self) -> FrameBatch | None:
        if self._closed:
            return None
        cfg = self.config
        level = STRENGTHS[cfg.strength - 1]
        while True:
            t = self._index / cfg.fps
            if t > cfg.duration:
                self._closed = True
                return None
            index = self._index
            self._index += 1
            active = 8 <= t < 12
            if cfg.perturbation == "frame_drop" and active and index % (5 - cfg.strength) == 0:
                continue
            break
        # Observation transforms leave the original latent schedule unchanged.
        motion_t = t
        flex = None
        yaw = 0.0
        if cfg.perturbation == "pause" and t >= 8:
            motion_t = 8 if t < 8 + 2 * level else t - 2 * level
        elif cfg.perturbation == "speed_drift" and t >= 3:
            motion_t = 3 + (t - 3) * (1 + .4 * level * (t - 3) / cfg.duration)
        elif cfg.perturbation == "partial_rom":
            flex = _cycle(t, self._body) * (1 - level)
        elif cfg.perturbation == "yaw":
            yaw = level * pi / 2
        pose = _body_pose(motion_t, self._body, cfg.negative, flex_override=flex, yaw_delta=yaw)
        poses = (pose,)
        if cfg.perturbation == "jitter" and active:
            pose = tuple(replace(p, x=p.x+self._rng.uniform(-.03,.03)*level, y=p.y+self._rng.uniform(-.03,.03)*level) for p in pose)
            poses = (pose,)
        elif cfg.perturbation == "occlusion" and active:
            count = 1 + cfg.strength
            poses = (tuple(replace(p, visibility=0.0) if i in (23,25,27,24)[:count] else p for i,p in enumerate(pose)),)
        elif cfg.perturbation == "camera_obstruction" and 8 <= t < 8 + 3 * level:
            poses = (tuple(replace(p, visibility=0.0, presence=0.0) for p in pose),)
        elif cfg.perturbation == "dropout" and active and index % 4 < cfg.strength:
            poses = ()
        elif cfg.perturbation == "second_person" and 8 <= t < 8 + 4 * level:
            poses = (pose, tuple(replace(p, x=p.x + .2 * level) for p in pose))
        elif cfg.perturbation == "reentry" and 8 <= t < 8 + 4 * level:
            poses = ()
        elif cfg.perturbation == "left_right_swap" and 8 <= t < 8 + 4 * level:
            by_name = {p.name:p for p in pose}
            poses = (tuple(replace(by_name[("right_"+p.name[5:]) if p.name.startswith("left_") else ("left_"+p.name[6:]) if p.name.startswith("right_") else p.name], name=p.name) for p in pose),)
        if cfg.negative == "exit_reenter" and 8 <= t < 14:
            poses = ()
        if cfg.perturbation == "timestamp_gap" and t >= 8:
            t += .8 * level
        missing = missing_between(self._previous, t, cfg.fps)
        slot = nominal_slot(t,cfg.fps)
        status = "missing" if not poses else "ok"
        if not poses:
            missing = tuple(sorted(set(missing) | {slot}))
        batch = FrameBatch(t, poses, cfg.width, cfg.height, nominal_fps=cfg.fps,
            source_id=f"development-{cfg.seed}", source_kind="synthetic", status=status,
            missing_slots=missing)
        try:
            result = self._validator.accept(batch)
        except ValueError:
            self._closed = True
            raise
        self._previous = t
        return result

    def close(self) -> None:
        self._closed = True
