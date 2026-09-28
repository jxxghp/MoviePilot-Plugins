from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeSettings:
    """单个插件实例的推理运行配置"""

    model_dir: Path
    data_root: Path
    tile: int = 256
    context: int = 32
    gpu_index: int = 0

    @property
    def model_path(self) -> Path:
        return self.model_dir / "2x-StarSample-V2-Lite.safetensors"

    @property
    def animesr_model_path(self) -> Path:
        return self.model_dir / "AnimeSR_v2.pth"

    @property
    def log_root(self) -> Path:
        return self.data_root / "logs"

    @property
    def device(self) -> str:
        return f"cuda:{self.gpu_index}"
