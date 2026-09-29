"""One bounded plugin process. No metadata database handle is passed to plugins."""
import json
import sys
from pathlib import Path

from .domain import Bundle, DatasetSpec, Failure, HarnessError, WorkResult, WorkUnit
from .plugins import ExecutionContext, Registry
from .store import write_json


def main():
    request=json.loads(Path(sys.argv[1]).read_text())
    spec=DatasetSpec.model_validate(request['spec'])
    unit=WorkUnit.model_validate(request['unit'])
    ctx=ExecutionContext(spec,Path(request['output_dir']),{
        key:(Bundle.model_validate(value['bundle']),Path(value['directory'])) for key,value in request['inputs'].items()})
    plugin=Registry().get(unit.plugin_id)
    result=None
    try:
        result=WorkResult.model_validate(plugin.execute(ctx,unit))
        if result.status=='succeeded':
            issues=plugin.validate(ctx,result)
            if any(i.severity in {'error','fatal'} for i in issues):
                result=WorkResult(status='quarantined',bundle=result.bundle,issues=issues)
    except HarnessError as exc:
        result=WorkResult(status='failed_retryable' if exc.failure.retryable else 'failed_final',failure=exc.failure)
    except Exception as exc:
        result=WorkResult(status='failed_final',failure=Failure(code='PLUGIN_EXCEPTION',message=f'{type(exc).__name__}: {exc}',component=unit.plugin_id))
    finally:
        try:
            plugin.cleanup(ctx,result)
        except Exception as exc:
            result=WorkResult(status='failed_final',failure=Failure(code='PLUGIN_CLEANUP',message=str(exc),component=unit.plugin_id))
    write_json(Path(request['result_path']),result.model_dump(mode='json'))
    return 0 if result.status=='succeeded' else 2


if __name__=='__main__':
    raise SystemExit(main())
