"""DA3 metric depth API client; predictions are not simulator ground truth."""
from .client import ModelService, module_main


def call(*, action="submit", request=None, work=None, job_id=None, config=None, timeout_seconds=300):
    return ModelService(config).call("depth_anything", action=action, request=request, work=work,
                                   job_id=job_id, timeout_seconds=timeout_seconds)


if __name__ == "__main__":
    module_main("depth_anything")
