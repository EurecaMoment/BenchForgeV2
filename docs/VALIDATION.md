# Verification

The repository's executable checks are the source of truth for current code
behavior. Historical machine runs have been archived outside this repository
and are not release evidence for the current revision.

## Local checks

From the repository root:

```powershell
npm ci --prefix integrations
python -m pip install ".[production,research]"
python -m unittest discover -s tests -v
python quickstart.py --workspace runs/ci-demo
python examples/production_demo.py --workspace runs/ci-production
python integrations/spatialforge/smoke.py
python -m unittest discover -s integrations/tests -v
node --test integrations/spatialforge/tests/test_workbench.mjs integrations/spatialforge/tests/test_assessment_plan.mjs integrations/spatialforge/tests/test_workbench_request.mjs integrations/spatialforge/tests/test_workbench_feedback.mjs
node --test integrations/spatialforge/tests/test_parallel_sessions.mjs integrations/spatialforge/tests/test_synthesis_sessions.mjs integrations/spatialforge/tests/test_synthesis_scope.mjs integrations/spatialforge/tests/test_preparation_tool.mjs integrations/spatialforge/tests/test_preparation_products.mjs integrations/spatialforge/tests/test_plugin_contracts.mjs integrations/spatialforge/tests/test_delivery_review.mjs
```

The disposable `runs/` directories are ignored by Git. SpatialForge service,
desktop worker, simulator, and optional GPU checks are separately scoped in the
CI workflow because they require extra dependencies or host capabilities.

## Scope

Passing offline tests verifies only the code paths those tests exercise. It
does not certify a live model endpoint, GPU throughput, Isaac Sim behavior,
production deployment, or model quality. Those claims require a recorded run
against the named target environment and an explicit acceptance result.

CI runs the portable checks on Windows and Linux with Python 3.10 and 3.12.
Additional SpatialForge tests run on Python 3.12. Check the GitHub Actions result
for the exact revision before treating CI as passed.
