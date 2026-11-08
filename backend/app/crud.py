"""CRUD operations for Camera, Zone (camera-scoped) and Calibration
(camera-scoped), including calibration's derived pixels_per_meter calc."""
import datetime
from math import hypot
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

import logging
from pathlib import Path
import secrets

from . import auth, heatmap as heatmap_grid, models, risk, schemas

logger = logging.getLogger(__name__)

INITIAL_ADMIN_PASSWORD_FILE = Path(__file__).resolve().parent.parent / "data" / "initial_admin_password.txt"


# ----------------------------------------------------------------- cameras

def create_camera(db: Session, camera_in: schemas.CameraCreate) -> models.Camera:
    camera = models.Camera(**camera_in.model_dump())
    if camera.site_id is None:
        camera.site_id = get_default_site(db).id
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


def get_camera(db: Session, camera_id: int) -> Optional[models.Camera]:
    return db.get(models.Camera, camera_id)


def get_cameras(db: Session) -> List[models.Camera]:
    return list(db.scalars(select(models.Camera)))


def update_camera(
    db: Session, camera: models.Camera, camera_in: schemas.CameraUpdate
) -> models.Camera:
    for field, value in camera_in.model_dump(exclude_unset=True).items():
        setattr(camera, field, value)
    db.commit()
    db.refresh(camera)
    return camera


def delete_camera(db: Session, camera: models.Camera) -> List[int]:
    """Deletes the camera plus, for a fisheye camera, its virtual views
    (fisheye_parent_id is not a real FK, see models.Camera). Returns every
    deleted camera id so the caller can stop their workers."""
    deleted = [camera.id]
    for view in get_fisheye_views(db, camera.id):
        deleted.append(view.id)
        db.delete(view)
    db.delete(camera)
    db.commit()
    return deleted


def get_fisheye_views(db: Session, parent_id: int) -> List[models.Camera]:
    return list(db.scalars(
        select(models.Camera)
        .where(models.Camera.fisheye_parent_id == parent_id)
        .order_by(models.Camera.id)
    ))


def save_fisheye_views(
    db: Session, parent: models.Camera, views_in: List[schemas.FisheyeViewIn]
) -> tuple[List[models.Camera], List[int]]:
    """Makes `parent`'s views exactly `views_in`: updates the listed existing
    views, creates new ones, deletes the rest. Returns (views, deleted_ids)."""
    existing = {v.id: v for v in get_fisheye_views(db, parent.id)}
    kept: List[models.Camera] = []
    for v in views_in:
        view = existing.pop(v.id, None) if v.id is not None else None
        if view is None:
            view = models.Camera(
                source_type="fisheye_view", fisheye_parent_id=parent.id, is_enabled=True,
            )
            db.add(view)
        view.name = v.name
        view.view_direction_deg = v.direction_deg % 360
        view.view_tilt_deg = v.tilt_deg
        view.view_fov_deg = v.fov_deg
        kept.append(view)
    deleted = list(existing.keys())
    for view in existing.values():
        db.delete(view)
    db.commit()
    for view in kept:
        db.refresh(view)
    return kept, deleted


# ------------------------------------------------------ detection settings

def get_detection_settings(db: Session) -> models.DetectionSettings:
    """Singleton row (id=1); created with defaults on first access so the
    rest of the app never has to special-case a missing row."""
    settings = db.get(models.DetectionSettings, 1)
    if settings is None:
        settings = models.DetectionSettings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_detection_settings(
    db: Session, settings: models.DetectionSettings, data: schemas.DetectionSettingsUpdate
) -> models.DetectionSettings:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    return settings


# -------------------------------------------------------------- zone types

def create_zone_type(db: Session, zt_in: schemas.ZoneTypeCreate) -> models.ZoneType:
    zone_type = models.ZoneType(**zt_in.model_dump(), is_system=False)
    db.add(zone_type)
    db.commit()
    db.refresh(zone_type)
    return zone_type


def get_zone_type(db: Session, zone_type_id: int) -> Optional[models.ZoneType]:
    return db.get(models.ZoneType, zone_type_id)


def get_zone_types(db: Session) -> List[models.ZoneType]:
    return list(db.scalars(select(models.ZoneType)))


def update_zone_type(
    db: Session, zone_type: models.ZoneType, zt_in: schemas.ZoneTypeUpdate
) -> models.ZoneType:
    for field, value in zt_in.model_dump(exclude_unset=True).items():
        setattr(zone_type, field, value)
    db.commit()
    db.refresh(zone_type)
    return zone_type


def delete_zone_type(db: Session, zone_type: models.ZoneType) -> None:
    db.delete(zone_type)
    db.commit()


_PROWLING_TYPE = dict(
    name="Car Prowling Watch",
    description="Parking bays: alert when someone goes car to car, lingers or crouches beside parked cars",
    applies_to="person", rule_prowling=True, default_prowling_min_vehicles=3.0,
)


def seed_default_zone_types(db: Session) -> None:
    existing = get_zone_types(db)
    if existing:
        # Built-in types added in a later release still reach existing databases (matched by
        # rule, not name, since admins can rename them).
        if not any(zt.rule_prowling for zt in existing):
            db.add(models.ZoneType(**_PROWLING_TYPE, is_system=True))
            db.commit()
        return
    defaults = [
        dict(name="Pedestrian Exclusion", description="No pedestrian entry allowed",
             applies_to="person", rule_exclusion=True),
        dict(name="Vehicle Exclusion", description="No vehicle entry allowed",
             applies_to="vehicle", rule_exclusion=True),
        dict(name="Vehicle Speed Limit 10km/h", description="Car park speed limit",
             applies_to="vehicle", default_max_speed_kmh=10.0),
        dict(name="Vehicle Speed Limit 15km/h", description="Truck/vehicle speed limit",
             applies_to="vehicle", default_max_speed_kmh=15.0),
        dict(name="Vehicle Stop Required", description="Vehicles must come to a stop before continuing",
             applies_to="vehicle", rule_stop_required=True, default_stop_min_seconds=1.0),
        _PROWLING_TYPE,
    ]
    for d in defaults:
        db.add(models.ZoneType(**d, is_system=True))
    db.commit()


# ------------------------------------------------------------------- zones

def create_zone(db: Session, zone_in: schemas.ZoneCreate) -> models.Zone:
    """zone_in's rule fields are optional overrides; anything left unset is
    copied from its zone_type."""
    zone_type = get_zone_type(db, zone_in.zone_type_id)
    if zone_type is None:
        raise ValueError(f"zone_type_id {zone_in.zone_type_id} does not exist")

    data = zone_in.model_dump(exclude_unset=True, exclude={"zone_type_id"})
    resolved = {
        "camera_id": zone_in.camera_id,
        "zone_type_id": zone_in.zone_type_id,
        "name": zone_in.name,
        "polygon_points": zone_in.polygon_points,
        "applies_to": data.get("applies_to", zone_type.applies_to),
        "rule_exclusion": data.get("rule_exclusion", zone_type.rule_exclusion),
        "max_speed_kmh": data.get("max_speed_kmh", zone_type.default_max_speed_kmh),
        "rule_stop_required": data.get("rule_stop_required", zone_type.rule_stop_required),
        "stop_min_seconds": data.get("stop_min_seconds", zone_type.default_stop_min_seconds),
        "rule_prowling": data.get("rule_prowling", zone_type.rule_prowling),
        "prowling_min_vehicles": data.get("prowling_min_vehicles", zone_type.default_prowling_min_vehicles),
        "time_restriction_enabled": data.get(
            "time_restriction_enabled", zone_type.time_restriction_enabled
        ),
        "from_time": data.get("from_time", zone_type.default_from_time),
        "to_time": data.get("to_time", zone_type.default_to_time),
    }
    zone = models.Zone(**resolved)
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return zone


def get_zone(db: Session, zone_id: int) -> Optional[models.Zone]:
    return db.get(models.Zone, zone_id)


def get_zones(db: Session, camera_id: Optional[int] = None) -> List[models.Zone]:
    stmt = select(models.Zone)
    if camera_id is not None:
        stmt = stmt.where(models.Zone.camera_id == camera_id)
    return list(db.scalars(stmt))


def update_zone(
    db: Session, zone: models.Zone, zone_in: schemas.ZoneUpdate
) -> models.Zone:
    for field, value in zone_in.model_dump(exclude_unset=True).items():
        setattr(zone, field, value)
    db.commit()
    db.refresh(zone)
    return zone


def delete_zone(db: Session, zone: models.Zone) -> None:
    db.query(models.Camera).filter(models.Camera.restricted_zone_id == zone.id).update(
        {models.Camera.restricted_zone_id: None}
    )
    db.delete(zone)
    db.commit()


# ------------------------------------------------------------- calibration

def _pixel_distance(points: List[List[float]]) -> float:
    # first segment: the reference line, or side 1->2 of a 4-point rectangle
    (x1, y1), (x2, y2) = points[0], points[1]
    return hypot(x2 - x1, y2 - y1)


def create_calibration(
    db: Session, cal_in: schemas.CalibrationCreate
) -> models.Calibration:
    pixels_per_meter = _pixel_distance(cal_in.line_points) / cal_in.real_world_meters
    calibration = models.Calibration(
        **cal_in.model_dump(), pixels_per_meter=pixels_per_meter, is_active=False
    )
    db.add(calibration)
    db.commit()
    db.refresh(calibration)
    return calibration


def get_calibration(db: Session, cal_id: int) -> Optional[models.Calibration]:
    return db.get(models.Calibration, cal_id)


def get_calibrations(db: Session, camera_id: Optional[int] = None) -> List[models.Calibration]:
    stmt = select(models.Calibration)
    if camera_id is not None:
        stmt = stmt.where(models.Calibration.camera_id == camera_id)
    return list(db.scalars(stmt))


def get_active_calibration(db: Session, camera_id: int) -> Optional[models.Calibration]:
    return db.scalar(
        select(models.Calibration).where(
            models.Calibration.camera_id == camera_id,
            models.Calibration.is_active == True,  # noqa: E712
        )
    )


def update_calibration(
    db: Session, calibration: models.Calibration, cal_in: schemas.CalibrationUpdate
) -> models.Calibration:
    updates = cal_in.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(calibration, field, value)
    if "line_points" in updates or "real_world_meters" in updates:
        calibration.pixels_per_meter = (
            _pixel_distance(calibration.line_points) / calibration.real_world_meters
        )
    db.commit()
    db.refresh(calibration)
    return calibration


def delete_calibration(db: Session, calibration: models.Calibration) -> None:
    db.delete(calibration)
    db.commit()


def activate_calibration(
    db: Session, calibration: models.Calibration
) -> models.Calibration:
    # only deactivate other calibrations for the SAME camera -- each camera
    # has its own independent active calibration.
    db.query(models.Calibration).filter(
        models.Calibration.camera_id == calibration.camera_id
    ).update({models.Calibration.is_active: False})
    calibration.is_active = True
    db.commit()
    db.refresh(calibration)
    return calibration


# -------------------------------------------------------------- roles/users

def create_role(db: Session, role_in: schemas.RoleCreate) -> models.Role:
    role = models.Role(**role_in.model_dump(), is_system=False)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def get_role(db: Session, role_id: int) -> Optional[models.Role]:
    return db.get(models.Role, role_id)


def get_roles(db: Session) -> List[models.Role]:
    return list(db.scalars(select(models.Role)))


def update_role(db: Session, role: models.Role, role_in: schemas.RoleUpdate) -> models.Role:
    for field, value in role_in.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    db.commit()
    db.refresh(role)
    return role


def get_users_by_role(db: Session, role_id: int) -> List[models.User]:
    return list(db.scalars(select(models.User).where(models.User.role_id == role_id)))


def delete_role(db: Session, role: models.Role) -> None:
    db.delete(role)
    db.commit()


def create_user(db: Session, user_in: schemas.UserCreate) -> models.User:
    password_hash, salt = auth.hash_password(user_in.password)
    user = models.User(
        username=user_in.username,
        password_hash=password_hash,
        password_salt=salt,
        role_id=user_in.role_id,
        is_system=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, user_id: int) -> Optional[models.User]:
    return db.get(models.User, user_id)


def get_user_by_username(db: Session, username: str) -> Optional[models.User]:
    return db.scalar(select(models.User).where(models.User.username == username))


def get_users(db: Session) -> List[models.User]:
    return list(db.scalars(select(models.User)))


def update_user(db: Session, user: models.User, user_in: schemas.UserUpdate) -> models.User:
    for field, value in user_in.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


def reset_password(db: Session, user: models.User, new_password: str) -> models.User:
    user.password_hash, user.password_salt = auth.hash_password(new_password)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: models.User) -> None:
    db.delete(user)
    db.commit()


def seed_default_admin(db: Session) -> None:
    admin_role = db.scalar(select(models.Role).where(models.Role.is_system == True))  # noqa: E712
    if admin_role is None:
        admin_role = models.Role(name="Admin", pages=schemas.PAGE_KEYS, is_system=True)
        db.add(admin_role)
        db.commit()
        db.refresh(admin_role)

    if get_user_by_username(db, "admin") is None:
        # No password in source: a random one-time password, shown once in the
        # server log, that must be changed at first login.
        initial_password = secrets.token_urlsafe(12)
        password_hash, salt = auth.hash_password(initial_password)
        db.add(
            models.User(
                username="admin",
                password_hash=password_hash,
                password_salt=salt,
                role_id=admin_role.id,
                is_system=True,
                must_change_password=True,
            )
        )
        db.commit()
        # Also in a local file: a console line is easy to miss (and buried in server.log on a site
        # server). backend/data is git-ignored; the file is deleted when the password is changed.
        INITIAL_ADMIN_PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
        INITIAL_ADMIN_PASSWORD_FILE.write_text(
            "Tiam one-time admin login\n"
            "username: admin\n"
            f"password: {initial_password}\n"
            "You must choose a new password at first login; this file is then deleted.\n",
            encoding="utf-8",
        )
        logger.warning("Created user 'admin' with one-time password: %s (also in %s)", initial_password, INITIAL_ADMIN_PASSWORD_FILE)
        print(f"*** Tiam: created user 'admin' with one-time password: {initial_password} "
              f"(also in {INITIAL_ADMIN_PASSWORD_FILE}) ***", flush=True)


# ------------------------------------------------------------------ events

def create_event(db: Session, event: dict) -> models.Event:
    """Persists a raw vision_engine event dict, scoring it via risk.py."""
    policy_type, risk_score = risk.score_event(event)
    row = models.Event(
        camera_id=event.get("camera_id"),
        zone_id=int(event["zone_id"]) if event.get("zone_id") is not None else None,
        zone_name=event.get("zone_name", ""),
        event_type=event.get("type"),
        policy_type=policy_type,
        risk_score=risk_score,
        track_id=event.get("track_id"),
        raw_payload=event,
        timestamp=datetime.datetime.fromtimestamp(event["timestamp"]),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_event(db: Session, event_id: int) -> Optional[models.Event]:
    return db.get(models.Event, event_id)


def get_events(
    db: Session,
    status: Optional[str] = None,
    camera_id: Optional[int] = None,
    min_risk: Optional[int] = None,
    max_risk: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
    verdict: Optional[str] = None,
) -> List[models.Event]:
    """verdict: None = everything except AI-rejected; "all"; a verdict; "unverified" (error/skipped);
    "none" (not sent to the AI)."""
    stmt = select(models.Event).order_by(models.Event.timestamp.desc())
    if verdict is None:
        stmt = stmt.where((models.Event.vlm_verdict.is_(None)) | (models.Event.vlm_verdict != "rejected"))
    elif verdict == "unverified":
        stmt = stmt.where(models.Event.vlm_status.in_(["error", "skipped"]))
    elif verdict == "none":
        stmt = stmt.where(models.Event.vlm_status == "none")
    elif verdict != "all":
        stmt = stmt.where(models.Event.vlm_verdict == verdict)
    if status is not None:
        stmt = stmt.where(models.Event.status == status)
    else:
        # Dismissing deletes an event, so "All" means every live event; never
        # surface a leftover row still marked dismissed.
        stmt = stmt.where(models.Event.status != "dismissed")
    if camera_id is not None:
        stmt = stmt.where(models.Event.camera_id == camera_id)
    if min_risk is not None:
        stmt = stmt.where(models.Event.risk_score >= min_risk)
    if max_risk is not None:
        stmt = stmt.where(models.Event.risk_score <= max_risk)
    stmt = stmt.offset(offset).limit(limit)
    return list(db.scalars(stmt))


def update_event(
    db: Session, event: models.Event, status: Optional[str] = None, risk_score: Optional[int] = None
) -> models.Event:
    if status is not None:
        event.status = status
    if risk_score is not None:
        event.risk_score = risk_score
    db.commit()
    db.refresh(event)
    return event


def delete_events(db: Session, ids: list[int]) -> list[int]:
    """Hard-deletes events (and their comments). Returns the ids that
    actually existed, so the caller can remove their snapshot files."""
    existing = list(db.scalars(select(models.Event.id).where(models.Event.id.in_(ids))))
    if existing:
        # Comments removed explicitly rather than relying on the FK's ON DELETE
        # CASCADE, which older databases may not have been created with.
        db.execute(delete(models.EventComment).where(models.EventComment.event_id.in_(existing)))
        db.execute(delete(models.Event).where(models.Event.id.in_(existing)))
        db.commit()
    return existing


def bulk_update_event_status(db: Session, ids: list[int], status: str) -> int:
    result = db.execute(
        update(models.Event).where(models.Event.id.in_(ids)).values(status=status)
    )
    db.commit()
    return result.rowcount


def mark_event_has_snapshot(db: Session, event: models.Event) -> None:
    event.has_snapshot = True
    db.commit()


def create_comment(db: Session, event_id: int, text: str) -> models.EventComment:
    comment = models.EventComment(
        event_id=event_id, text=text, created_at=datetime.datetime.now()
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def get_comments(db: Session, event_id: int) -> List[models.EventComment]:
    stmt = (
        select(models.EventComment)
        .where(models.EventComment.event_id == event_id)
        .order_by(models.EventComment.created_at.asc())
    )
    return list(db.scalars(stmt))


def to_alert_payload(event: models.Event) -> dict:
    return {
        "event_id": event.id,
        "camera_id": event.camera_id,
        "zone_name": event.zone_name,
        "policy_type": event.policy_type,
        "event_type": event.event_type,
        "risk_score": event.risk_score,
        "vlm_status": event.vlm_status or "none",
        "timestamp": event.timestamp.isoformat(),
    }


# ----------------------------------------------------------------- heatmap

def upsert_heatmap_counts(
    db: Session, camera_id: int, day: str, deltas: dict[tuple[str, int, int], int]
) -> None:
    """Adds `deltas` (keyed by (metric, grid_row, grid_col)) onto whatever
    is already stored for (camera_id, day, ...), creating rows as needed.
    Called periodically by each camera worker with the counts it has
    accumulated in memory since its last flush -- never with raw per-frame
    writes, so this stays cheap regardless of camera frame rate."""
    if not deltas:
        return
    existing = {
        (row.metric, row.grid_row, row.grid_col): row
        for row in db.scalars(
            select(models.HeatmapCell).where(
                models.HeatmapCell.camera_id == camera_id,
                models.HeatmapCell.day == day,
            )
        )
    }
    for (metric, grid_row, grid_col), delta in deltas.items():
        row = existing.get((metric, grid_row, grid_col))
        if row is None:
            db.add(models.HeatmapCell(
                camera_id=camera_id, day=day, metric=metric,
                grid_row=grid_row, grid_col=grid_col, count=delta,
            ))
        else:
            row.count += delta
    db.commit()


def get_heatmap_grid(
    db: Session, camera_id: int, metric: str, start_day: str, end_day: str
) -> list[list[int]]:
    """Returns a GRID_ROWS x GRID_COLS grid of summed counts for `metric` (or
    heatmap.USAGE_ALL = every object class) on
    this camera, across every day in [start_day, end_day] (inclusive,
    "YYYY-MM-DD" strings -- lexicographic comparison is correct for ISO
    dates)."""
    grid = [[0] * heatmap_grid.GRID_COLS for _ in range(heatmap_grid.GRID_ROWS)]
    if metric == heatmap_grid.USAGE_ALL:
        # Every object class summed -- anything that isn't a violation metric.
        metric_filter = ~models.HeatmapCell.metric.startswith(heatmap_grid.VIOLATION_METRIC_PREFIX)
    else:
        metric_filter = models.HeatmapCell.metric == metric
    rows = db.scalars(
        select(models.HeatmapCell).where(
            models.HeatmapCell.camera_id == camera_id,
            metric_filter,
            models.HeatmapCell.day >= start_day,
            models.HeatmapCell.day <= end_day,
        )
    )
    for row in rows:
        grid[row.grid_row][row.grid_col] += row.count
    return grid


# ------------------------------------------------------------------- sites

def get_sites(db: Session) -> List[models.Site]:
    return list(db.scalars(select(models.Site).order_by(models.Site.id)))


def get_site(db: Session, site_id: int) -> Optional[models.Site]:
    return db.get(models.Site, site_id)


def get_default_site(db: Session) -> models.Site:
    site = db.scalar(select(models.Site).order_by(models.Site.id))
    if site is None:
        site = models.Site(name="Main car park")
        db.add(site)
        db.commit()
        db.refresh(site)
    return site


def seed_default_site(db: Session) -> None:
    """One site always exists; cameras created before sites existed are assigned to it."""
    site = get_default_site(db)
    db.execute(update(models.Camera).where(models.Camera.site_id.is_(None)).values(site_id=site.id))
    db.commit()


def update_site(db: Session, site: models.Site, data: "schemas.SiteUpdate") -> models.Site:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(site, field, value)
    db.commit()
    db.refresh(site)
    return site


def mark_event_has_clip(db: Session, event_id: int) -> None:
    db.execute(update(models.Event).where(models.Event.id == event_id).values(has_clip=True))
    db.commit()
