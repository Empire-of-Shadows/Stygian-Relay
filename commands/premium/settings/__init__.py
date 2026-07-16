"""Premium settings seam. `config.py` is the only per-bot file; the loader is portable."""

from .loader import PremiumSettings, load_settings

__all__ = ["PremiumSettings", "load_settings"]
