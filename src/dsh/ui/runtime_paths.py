"""Resolve paths shared by workbench Python entry points."""

from pathlib import Path
import sys


DSH_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = DSH_ROOT.parent
CHECKOUT_ROOT = (
    SOURCE_ROOT.parent
    if SOURCE_ROOT.name == 'src' and (SOURCE_ROOT / 'benchforge_core/__init__.py').is_file()
    else None
)
DEPLOYMENT_ROOT = (CHECKOUT_ROOT or DSH_ROOT.parent) / '.deployment'


def use_checkout_core():
    """Make the checkout's Python core importable when running a source script."""
    source = str(SOURCE_ROOT)
    if CHECKOUT_ROOT is not None and source not in sys.path:
        sys.path.insert(0, source)
