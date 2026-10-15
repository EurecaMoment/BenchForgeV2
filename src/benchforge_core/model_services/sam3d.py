"""SAM3D paired Mesh and Gaussian API client; no local model startup."""
from .client import ModelService, module_main


def call(*, action="submit", request=None, work=None, job_id=None, config=None, timeout_seconds=300):
    return ModelService(config).call("sam3d", action=action, request=request, work=work,
                                   job_id=job_id, timeout_seconds=timeout_seconds)


if __name__ == "__main__":
    module_main("sam3d")
