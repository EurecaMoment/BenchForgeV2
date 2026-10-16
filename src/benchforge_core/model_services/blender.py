"""Blender Cycles CUDA API client; Blender execution belongs to FIT."""
from .client import ModelService, module_main


def call(*, action="submit", request=None, work=None, job_id=None, config=None, timeout_seconds=3600):
    return ModelService(config).call("blender", action=action, request=request, work=work,
                                    job_id=job_id, timeout_seconds=timeout_seconds)


if __name__ == "__main__":
    module_main("blender")
