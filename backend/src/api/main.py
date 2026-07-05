from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.routes import sim, volume
from core.config import settings
from core.logging import get_logger, setup_logging
from reconstruction.dataset_utils import list_odm_datasets

setup_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Data directory:  %s", settings.data_dir)
    logger.info("ODM datasets:    %s", settings.odm_datasets_dir)
    logger.info("OpenSfM project: %s", settings.opensfm_project_dir)
    logger.info("SITL endpoint:   %s", settings.sitl_connection_url)
    yield


app = FastAPI(
    title="Indoor Stockpile Drone API",
    version="0.1.0",
    description=(
        "Prototype API for GPS-denied indoor stockpile measurement: simulated "
        "orbit flights (PX4 SITL / MAVSDK), OpenSfM reconstruction and "
        "Open3D-based volume estimation."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sim.router)
app.include_router(volume.router)


class HealthResponse(BaseModel):
    status: str


class DatasetListResponse(BaseModel):
    datasets: list[str]


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness check."""
    return HealthResponse(status="ok")


@app.get("/datasets", response_model=DatasetListResponse)
def list_datasets() -> DatasetListResponse:
    """List example datasets (folders containing images) under data/odm/."""
    return DatasetListResponse(datasets=list_odm_datasets())
