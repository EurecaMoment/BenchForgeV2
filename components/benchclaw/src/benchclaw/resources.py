"""Resolve bundled legacy resources in source checkouts and installed wheels."""
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent


def resource_root():
    packaged = PACKAGE_ROOT / "resources"
    if packaged.is_dir():
        return packaged
    source = PACKAGE_ROOT.parents[1]
    if source.is_dir():
        return source
    raise FileNotFoundError("BenchClaw resources are unavailable")


def resource_path(*parts):
    return resource_root().joinpath(*parts)


def benchclaw_root():
    return resource_path("BenchClaw")
