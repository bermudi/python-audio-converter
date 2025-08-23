from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 not supported per pyproject
    tomllib = None  # type: ignore

from tomlkit import dumps as toml_dumps


DEFAULT_CONFIG_PATH = Path("~/.config/python-audio-converter/config.toml").expanduser()
ENV_PREFIX = "PAC_"


class PacSettings(BaseSettings):
    """Global settings for python-audio-converter.

    Priority (lowest -> highest):
    - Class defaults below
    - TOML file at `config_path` (default: ~/.config/python-audio-converter/config.toml)
    - Environment variables with prefix PAC_
    - CLI overrides passed to `load_settings(overrides=...)`
    """

    # Logging
    log_level: str = Field(default="INFO", description="Console log level")
    log_json: Optional[str] = Field(default=None, description="Path for structured JSON log file")

    # convert-dir defaults
    tvbr: int = Field(default=96, description="qaac true VBR quality (around 256 kbps)")
    vbr: int = Field(default=5, description="libfdk_aac/fdkaac VBR quality 1..5")
    workers: Optional[int] = Field(default=None, description="Parallel workers; None=auto (CPU cores)")
    hash_streaminfo: bool = Field(default=False, description="Compute FLAC STREAMINFO MD5 during scan")
    force: bool = Field(default=False, description="Force re-encode regardless of DB state")
    commit_batch_size: int = Field(default=32, description="Batch DB commits per N files")

    # Config source/path (not persisted as part of effective config when writing)
    config_path: Path = Field(default=DEFAULT_CONFIG_PATH, exclude=True)

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore")

    @staticmethod
    def default_config_path() -> Path:
        return DEFAULT_CONFIG_PATH

    @classmethod
    def _toml_file_source(cls, config_path: Path) -> Dict[str, Any]:
        """Read settings from a TOML file if it exists; return dict values.

        Unknown keys are ignored by pydantic via extra="ignore".
        """
        if not config_path or not config_path.exists():
            return {}
        if tomllib is None:
            return {}
        with config_path.open("rb") as f:
            data = tomllib.load(f)
        # Flatten nested tables if we later decide to group keys; for now expect flat
        if not isinstance(data, dict):
            return {}
        return data  # type: ignore[return-value]

    @classmethod
    def load(
        cls,
        *,
        config_path: Optional[Path] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> "PacSettings":
        """Load settings from defaults + TOML + env + CLI overrides.

        - config_path: path to TOML config; defaults to ~/.config/python-audio-converter/config.toml
        - overrides: dict of CLI values (None values are ignored)
        """
        cp = config_path or DEFAULT_CONFIG_PATH
        file_values = cls._toml_file_source(cp)
        # Build settings in two steps so that env can override file, and CLI overrides override env
        base = cls(**file_values)  # file + env via pydantic
        if overrides:
            non_none = {k: v for k, v in overrides.items() if v is not None}
        else:
            non_none = {}
        # Re-construct with overrides applied; carry forward config_path
        merged = base.model_dump()
        merged.update(non_none)
        settings = cls(**merged)
        settings.config_path = cp
        return settings

    def to_toml(self) -> str:
        """Serialize effective settings (excluding ephemeral fields) to TOML string."""
        data = self.model_dump(exclude={"config_path"})
        return toml_dumps(data)

    def write(self, path: Optional[Path] = None) -> Path:
        """Write effective config to TOML at `path` (or default path). Creates parent dirs.

        Returns the path written.
        """
        target = path or self.config_path or DEFAULT_CONFIG_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        content = self.to_toml()
        target.write_text(content, encoding="utf-8")
        return target


def cli_overrides_from_args(args: Any) -> Dict[str, Any]:
    """Extract known settings keys from argparse Namespace into an overrides dict.

    Unknown keys are ignored; None values are preserved for filtering by `load()`.
    """
    keys = {
        "log_level",
        "log_json",
        "tvbr",
        "vbr",
        "workers",
        "hash_streaminfo",
        "force",
        "commit_batch_size",
    }
    result: Dict[str, Any] = {}
    for k in keys:
        if hasattr(args, k):
            result[k] = getattr(args, k)
    return result
