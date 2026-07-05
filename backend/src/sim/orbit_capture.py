"""Simulate an orbit flight around a stockpile with camera trigger events.

Two modes, chosen automatically by run_orbit_sim:

- "mavsdk":  a PX4 SITL instance is reachable on settings.sitl_connection_url
  → the orbit is actually flown via MAVSDK offboard position setpoints in
  the local NED frame (no GPS semantics — fits the indoor, GPS-denied theme).
- "offline": no SITL (tests, CI, laptops) → the same camera poses are
  computed analytically and only logged, so the API works anywhere.

Camera captures are log events only; no real camera is triggered.
"""

import asyncio
import math
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from core.config import settings
from core.logging import get_logger
from sim.sitl_runner import is_sitl_reachable

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class CameraTrigger:
    index: int
    north_m: float
    east_m: float
    up_m: float
    yaw_deg: float


@dataclass
class SimResult:
    dataset_id: str
    mode: str  # "mavsdk" | "offline"
    num_triggers: int
    triggers: list[CameraTrigger] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


def orbit_poses(radius_m: float, altitude_m: float, num_triggers: int) -> list[CameraTrigger]:
    """Camera poses evenly spaced on a circle, each facing the orbit centre."""
    poses: list[CameraTrigger] = []
    for i in range(num_triggers):
        angle = 2 * math.pi * i / num_triggers
        poses.append(
            CameraTrigger(
                index=i,
                north_m=radius_m * math.cos(angle),
                east_m=radius_m * math.sin(angle),
                up_m=altitude_m,
                yaw_deg=math.degrees(angle + math.pi) % 360.0,
            )
        )
    return poses


async def run_orbit_sim(
    dataset_id: str,
    radius_m: float = 5.0,
    altitude_m: float = 3.0,
    num_triggers: int = 24,
    trigger_interval_s: float = 2.0,
) -> SimResult:
    """Fly (or simulate) a circular orbit and collect camera trigger events."""
    poses = orbit_poses(radius_m, altitude_m, num_triggers)
    logs: list[str] = []

    if _mavsdk_available() and is_sitl_reachable(timeout_s=1.0):
        _log(logs, f"SITL reachable on {settings.sitl_connection_url} — flying via MAVSDK")
        await _fly_orbit_mavsdk(poses, altitude_m, trigger_interval_s, logs)
        mode = "mavsdk"
    else:
        _log(logs, "SITL not reachable — offline simulation (poses computed, nothing flown)")
        for pose in poses:
            _log(logs, _trigger_message(pose))
        mode = "offline"

    _log(logs, f"Orbit complete: {len(poses)} camera triggers")
    return SimResult(
        dataset_id=dataset_id,
        mode=mode,
        num_triggers=len(poses),
        triggers=poses,
        logs=logs,
    )


async def _fly_orbit_mavsdk(
    poses: list[CameraTrigger],
    altitude_m: float,
    trigger_interval_s: float,
    logs: list[str],
) -> None:
    """Connect, arm, take off, fly the orbit with offboard NED setpoints, land."""
    from mavsdk import System
    from mavsdk.offboard import PositionNedYaw

    drone = System()
    _log(logs, f"Connecting to {settings.sitl_connection_url}")
    await drone.connect(system_address=settings.sitl_connection_url)
    await _await_state(
        drone.core.connection_state(), lambda s: s.is_connected, 15.0, "MAVSDK connection"
    )
    await _await_state(
        drone.telemetry.health(),
        lambda h: h.is_local_position_ok and h.is_home_position_ok,
        60.0,
        "position estimate",
    )

    _log(logs, "Arming")
    await drone.action.arm()
    await drone.action.set_takeoff_altitude(altitude_m)
    _log(logs, f"Taking off to {altitude_m:.1f} m")
    await drone.action.takeoff()
    await asyncio.sleep(8.0)  # SITL comfortably reaches takeoff altitude in this time

    # PX4 requires a setpoint to be streamed before offboard mode can start.
    await drone.offboard.set_position_ned(PositionNedYaw(0.0, 0.0, -altitude_m, 0.0))
    _log(logs, "Starting offboard orbit")
    try:
        await drone.offboard.start()
        for pose in poses:
            await drone.offboard.set_position_ned(
                PositionNedYaw(pose.north_m, pose.east_m, -pose.up_m, pose.yaw_deg)
            )
            await asyncio.sleep(trigger_interval_s)
            _log(logs, _trigger_message(pose))
        await drone.offboard.stop()
    finally:
        _log(logs, "Landing")
        await drone.action.land()
        await _await_state(
            drone.telemetry.in_air(), lambda in_air: not in_air, 60.0, "landing"
        )
        _log(logs, "Landed")


async def _await_state(
    stream: AsyncIterable[T],
    predicate: Callable[[T], bool],
    timeout_s: float,
    what: str,
) -> None:
    """Wait until a telemetry stream yields a value matching the predicate."""

    async def consume() -> None:
        async for item in stream:
            if predicate(item):
                return

    try:
        await asyncio.wait_for(consume(), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise RuntimeError(f"timed out after {timeout_s:.0f}s waiting for {what}") from exc


def _mavsdk_available() -> bool:
    try:
        import mavsdk  # noqa: F401
    except ImportError:
        return False
    return True


def _log(logs: list[str], message: str) -> None:
    logger.info(message)
    logs.append(message)


def _trigger_message(pose: CameraTrigger) -> str:
    return (
        f"Camera trigger {pose.index} at N {pose.north_m:.2f} m, "
        f"E {pose.east_m:.2f} m, alt {pose.up_m:.2f} m, yaw {pose.yaw_deg:.1f} deg"
    )
