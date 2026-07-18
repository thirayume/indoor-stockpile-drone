from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root when running from a source checkout; in Docker STOCKPILE_DATA_DIR
# is set to the mounted /data volume instead.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STOCKPILE_")

    data_dir: Path = _REPO_ROOT / "data"
    # Overrides the default <data_dir>/opensfm_project location; the alias is
    # the exact env var name (no STOCKPILE_ prefix), set in docker-compose.
    opensfm_project_root: Path | None = Field(
        default=None, validation_alias="OPEN_SFM_DATA_ROOT"
    )
    log_level: str = "INFO"
    # "*" is fine for a local prototype; set STOCKPILE_CORS_ORIGINS to a JSON
    # list (e.g. '["http://localhost:5173"]') to restrict it.
    cors_origins: list[str] = ["*"]
    sitl_connection_url: str = "udp://:14540"
    # Shell command used by sim.sitl_runner.start_sitl to launch PX4 SITL;
    # see that module's docstring for alternatives (source build, jMAVSim).
    sitl_command: str = (
        "docker run --rm -p 14540:14540/udp jonasvautherin/px4-gazebo-headless:1.14"
    )

    # --- ML segmentation (YOLOE open-vocabulary instance segmentation) ---
    # Weights auto-download into ml_models_dir on first use (needs a writable
    # data mount in Docker — the OpenSfM overlay compose file provides one).
    ml_models_dir: Path | None = None  # default: <data_dir>/models
    # Text-prompt variant; the prompt-free auto-detect model name is derived
    # from it ("-seg" -> "-seg-pf"). Sizes: 11s (fast) / 11m / 11l (accurate).
    ml_model: str = "yoloe-11s-seg.pt"
    # Low on purpose: aerial photos give open-vocab models weak confidences,
    # and the cross-photo vote (MIN_VOTE_SCORE) filters one-off detections.
    ml_confidence: float = 0.1
    ml_image_size: int = 1024
    # Split each photo into tiles^2 overlapping crops for inference. Objects
    # in nadir aerial shots are tiny at model resolution; tiling is the
    # standard fix. 1 = no tiling.
    ml_tiles: int = 2

    @property
    def ml_models_path(self) -> Path:
        return self.ml_models_dir or self.data_dir / "models"

    @property
    def odm_datasets_dir(self) -> Path:
        return self.data_dir / "odm"

    @property
    def opensfm_project_dir(self) -> Path:
        return self.opensfm_project_root or self.data_dir / "opensfm_project"


settings = Settings()
