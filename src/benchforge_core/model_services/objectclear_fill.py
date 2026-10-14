"""Independent objectclear_fill service client; inference is owned by the external server."""
from .client import ModelService, module_main


def call(*, action="submit", request=None, work=None, job_id=None, config=None, timeout_seconds=300):
    return ModelService(config).call("objectclear", action=action, request=request, work=work,
                                   job_id=job_id, timeout_seconds=timeout_seconds)


if __name__ == "__main__":
    module_main("objectclear")
