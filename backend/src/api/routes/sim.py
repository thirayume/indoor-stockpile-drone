from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sim.orbit_capture import run_orbit_sim

router = APIRouter(prefix="/sim", tags=["simulation"])


class OrbitRequest(BaseModel):
    dataset_id: str
    pattern: Literal["orbit", "grid"] = Field(
        default="orbit",
        description='"orbit" circles the pile; "grid" flies a lawnmower survey '
        "over a square of side 2 x radius_m.",
    )
    radius_m: float = Field(default=5.0, gt=0)
    altitude_m: float = Field(default=3.0, gt=0)
    num_triggers: int = Field(default=24, ge=1, le=1000, description="orbit pattern only")
    spacing_m: float = Field(default=2.0, gt=0.2, description="grid pattern only")
    trigger_interval_s: float = Field(default=2.0, gt=0, le=60)


class CameraTriggerModel(BaseModel):
    index: int
    north_m: float
    east_m: float
    up_m: float
    yaw_deg: float


class OrbitResponse(BaseModel):
    dataset_id: str
    mode: str
    pattern: str
    num_triggers: int
    triggers: list[CameraTriggerModel]
    logs: list[str]


@router.post("/orbit", response_model=OrbitResponse)
async def run_orbit(request: OrbitRequest) -> OrbitResponse:
    """Run an orbit flight (via MAVSDK if SITL is up, offline otherwise)."""
    try:
        result = await run_orbit_sim(
            dataset_id=request.dataset_id,
            radius_m=request.radius_m,
            altitude_m=request.altitude_m,
            num_triggers=request.num_triggers,
            trigger_interval_s=request.trigger_interval_s,
            pattern=request.pattern,
            spacing_m=request.spacing_m,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return OrbitResponse(
        dataset_id=result.dataset_id,
        mode=result.mode,
        pattern=request.pattern,
        num_triggers=result.num_triggers,
        triggers=[
            CameraTriggerModel(
                index=t.index, north_m=t.north_m, east_m=t.east_m, up_m=t.up_m, yaw_deg=t.yaw_deg
            )
            for t in result.triggers
        ],
        logs=result.logs,
    )
