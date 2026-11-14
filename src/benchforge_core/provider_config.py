"""Use the same provider registry in the checkout and in standalone core builds."""

import importlib.util
from pathlib import Path

try:
    from . import _provider_config as provider_config
except ImportError:
    source = Path(__file__).resolve().parents[1] / 'backend/benchforge_backend/provider_config.py'
    spec = importlib.util.spec_from_file_location('benchforge_provider_config', source)
    provider_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider_config)
