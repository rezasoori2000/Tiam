"""System page (spec 9.6): per-camera worker metrics, GPU, disk use of data/retail_* folders."""
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends

from .. import auth, camera_manager, detection_engine

router = APIRouter(prefix="/api/system", tags=["system"], dependencies=[Depends(auth.require_admin)])

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _gpu() -> list:
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            gpus = []
            for i in range(pynvml.nvmlDeviceGetCount()):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                name = pynvml.nvmlDeviceGetName(h)
                gpus.append({
                    "name": name.decode() if isinstance(name, bytes) else name,
                    "memory_used_mb": round(mem.used / 2**20), "memory_total_mb": round(mem.total / 2**20),
                    "utilization_pct": util.gpu,
                })
            return gpus
        finally:
            pynvml.nvmlShutdown()
    except Exception:  # no NVIDIA driver / pynvml: the page just shows "no GPU info"
        return []


def _folder_mb(path: Path) -> float:
    return round(sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 2**20, 1)


@router.get("/metrics")
def metrics():
    disk = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else Path("."))
    loaded, models = detection_engine.engine_info()
    return {
        "cameras": camera_manager.get_metrics(),
        "gpus": _gpu(),
        "models_loaded": [Path(m).name for m in models],
        "data_folders": {p.name: _folder_mb(p) for p in sorted(DATA_DIR.glob("retail_*")) if p.is_dir()},
        "disk_free_gb": round(disk.free / 2**30, 1),
        "disk_total_gb": round(disk.total / 2**30, 1),
        "verification_queue": None,  # phase 2 (AI verification)
    }
