"""Fisheye helpers: automatic lens-circle detection and "virtual camera"
views for splitting one fisheye camera into several normal-looking views.

A ceiling-mounted fisheye looks straight down, so a single flattened
(rectilinear, defisheye-style) image of the whole lens badly stretches
everything near the edge -- which is exactly where the aisles, walls and
people are. Instead, each view here is its own virtual pinhole camera placed
at the lens centre, turned to a compass direction (`yaw`) and tilted out from
straight down (`tilt`), with its own field of view (`fov`). Each one is
flattened on its own with the same equidistant ("f-theta") model the
defisheye library uses for a 180 degree lens, so every view looks like an
ordinary angled CCTV camera covering one side of the area.

All angles are in degrees. Circle ratios are fractions (0-1) of the raw
frame's width/height, as stored on models.Camera.fisheye_*.
"""
from typing import Optional, Tuple

import cv2
import numpy as np

# The edge of the calibrated lens circle is where the lens reaches 90 degrees
# off its optical axis (a ~180 degree circular fisheye, the norm for CCTV).
SRC_THETA_MAX = np.pi / 2

# Default split: 4 views, one per diagonal of the raw image (top-left,
# top-right, bottom-right, bottom-left). Direction 0 = towards the top of the
# raw fisheye image, increasing clockwise.
DEFAULT_VIEW_DIRECTIONS = (315.0, 45.0, 135.0, 225.0)
DEFAULT_VIEW_TILT = 55.0
DEFAULT_VIEW_FOV = 95.0

Circle = Tuple[float, float, float, float]  # cx, cy, rx, ry as frame ratios


def detect_lens_circle(frame: np.ndarray) -> Optional[Circle]:
    """Finds the bright lens image against the black surround and fits an
    ellipse to it. Returns None if nothing circle-like is found (e.g. a
    completely dark frame)."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    blur = cv2.GaussianBlur(gray, (15, 15), 0)
    _, mask = cv2.threshold(blur, 25, 255, cv2.THRESH_BINARY)
    kernel = np.ones((max(3, w // 80), max(3, w // 80)), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if len(contour) < 5 or cv2.contourArea(contour) < 0.1 * w * h:
        return None
    (cx, cy), (ew, eh), _angle = cv2.fitEllipse(contour)
    # fitEllipse's axes can come back rotated by 90 degrees; the lens is
    # axis-aligned in practice, so use the contour's bounding box to decide
    # which axis is horizontal.
    _x, _y, bw, bh = cv2.boundingRect(contour)
    rx, ry = (ew / 2, eh / 2) if (ew >= eh) == (bw >= bh) else (eh / 2, ew / 2)
    return (cx / w, cy / h, min(rx / w, 0.75), min(ry / h, 0.75))


def build_view_maps(
    src_w: int,
    src_h: int,
    circle: Circle,
    direction_deg: float,
    tilt_deg: float,
    fov_deg: float,
    out_w: int,
    out_h: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """cv2.remap lookup maps for one virtual camera view (see module doc)."""
    cx, cy = circle[0] * src_w, circle[1] * src_h
    rx, ry = circle[2] * src_w, circle[3] * src_h

    fov = np.radians(min(max(fov_deg, 20.0), 150.0))
    f = (out_w / 2.0) / np.tan(fov / 2.0)
    xs, ys = np.meshgrid(
        np.arange(out_w, dtype=np.float32) - out_w / 2.0 + 0.5,
        np.arange(out_h, dtype=np.float32) - out_h / 2.0 + 0.5,
    )
    # Rotated 180 degrees in-image so, for a ceiling mount, the far side
    # (horizon) is at the top of the view and the floor near the camera at
    # the bottom -- like a normal wall-mounted camera.
    rays = np.stack([-xs, -ys, np.full_like(xs, f)], axis=-1)
    rays /= np.linalg.norm(rays, axis=-1, keepdims=True)

    tilt = np.radians(min(max(tilt_deg, 0.0), 89.0))
    # Direction 0 = top of the raw image (-y), clockwise; convert to the
    # image-plane angle used for the rotation about the optical axis.
    yaw = np.radians(direction_deg - 90.0)
    rot_x = np.array([
        [1, 0, 0],
        [0, np.cos(tilt), np.sin(tilt)],
        [0, -np.sin(tilt), np.cos(tilt)],
    ])
    rot_z = np.array([
        [np.cos(yaw), -np.sin(yaw), 0],
        [np.sin(yaw), np.cos(yaw), 0],
        [0, 0, 1],
    ])
    # Tilt about x turns the view towards +y; pre-rotate by -90 degrees so
    # tilt alone (direction 90 -> yaw 0) looks along +x, then yaw it round.
    rot_align = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]])
    rays = rays @ (rot_z @ rot_align @ rot_x).T

    theta = np.arccos(np.clip(rays[..., 2], -1.0, 1.0))  # angle off lens axis
    phi = np.arctan2(rays[..., 1], rays[..., 0])
    r = theta / SRC_THETA_MAX  # equidistant: radius grows linearly with angle
    map_x = (cx + r * rx * np.cos(phi)).astype(np.float32)
    map_y = (cy + r * ry * np.sin(phi)).astype(np.float32)
    return map_x, map_y


def render_view(frame: np.ndarray, maps: Tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    return cv2.remap(
        frame, maps[0], maps[1],
        interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
    )
