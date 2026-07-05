"""Start/stop PX4 SITL and probe its MAVLink endpoint.

SITL is launched with a plain shell command taken from settings.sitl_command.
Typical choices:

  - docker (easiest, works everywhere):
        docker run --rm -p 14540:14540/udp jonasvautherin/px4-gazebo-headless:1.14
  - PX4 source build (Linux/WSL):
        make -C /path/to/PX4-Autopilot px4_sitl jmavsim
  - headless Gazebo source build:
        HEADLESS=1 make -C /path/to/PX4-Autopilot px4_sitl gazebo

All of these publish the MAVLink "onboard" API on udp://:14540, which is the
endpoint MAVSDK connects to (settings.sitl_connection_url).
"""

import shlex
import socket
import subprocess
import time
from dataclasses import dataclass

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SitlHandle:
    """A launched SITL instance; `process` is None when externally managed."""

    connection_url: str
    process: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None


def _udp_port(connection_url: str) -> int:
    """Extract the port from a MAVSDK-style URL like 'udp://:14540'."""
    try:
        return int(connection_url.rsplit(":", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"cannot parse UDP port from {connection_url!r}") from exc


def is_sitl_reachable(connection_url: str | None = None, timeout_s: float = 2.0) -> bool:
    """True if MAVLink datagrams are arriving on the SITL UDP endpoint.

    PX4 SITL pushes heartbeats to the onboard API port, so briefly binding it
    and waiting for any datagram is a cheap liveness probe; the socket is
    closed again before MAVSDK connects. Heuristic: a bind failure (port
    already held, e.g. by a running MAVSDK server) also reports False.
    """
    url = connection_url or settings.sitl_connection_url
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout_s)
        try:
            sock.bind(("0.0.0.0", _udp_port(url)))
            sock.recvfrom(1024)
            return True
        except OSError:
            return False


def start_sitl(wait_s: float = 60.0) -> SitlHandle:
    """Launch PX4 SITL via settings.sitl_command; wait until it is reachable."""
    command = settings.sitl_command
    logger.info("Starting SITL: %s", command)
    process = subprocess.Popen(shlex.split(command))
    handle = SitlHandle(connection_url=settings.sitl_connection_url, process=process)

    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if not handle.running:
            raise RuntimeError(f"SITL process exited early (command: {command})")
        if is_sitl_reachable(handle.connection_url, timeout_s=2.0):
            logger.info("SITL is up on %s", handle.connection_url)
            return handle

    stop_sitl(handle)
    raise TimeoutError(f"SITL did not become reachable within {wait_s:.0f}s")


def stop_sitl(handle: SitlHandle) -> None:
    """Terminate a SITL process started by start_sitl (no-op if external)."""
    if handle.process is None or not handle.running:
        return
    logger.info("Stopping SITL (pid %d)", handle.process.pid)
    handle.process.terminate()
    try:
        handle.process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("SITL did not terminate in time; killing it")
        handle.process.kill()
        handle.process.wait(timeout=10)
