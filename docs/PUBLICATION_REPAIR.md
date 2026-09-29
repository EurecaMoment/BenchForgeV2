# Publication repair, 2026-09-30

The published `6cc177c` tree contained only README, license/gitignore and five
SpatialForge adapter files. The README referred to `benchforge.py`, `pyproject.toml`,
`src/`, examples and tests that existed only in a different local checkout.
Consequently the published repository could not execute its documented setup.
The local six-test result was not a test of the published tree.

This change restores the tracked BenchForge source snapshot `cf5cc8c`, including
the launcher, pinned DSH dependency manifest, package data, reusable production
algorithms, examples, tests and Windows/Linux CI. V2 entry instructions point at
the correct repository. Historical BenchForge validation remains explicitly
upstream evidence, not new V2 acceptance.

The SpatialForge status client now calls the service's authenticated POST routes.
The production DSH tool definitions and delivery-review modules are included with
configuration-based imports, service URL and credentials. `setup
--spatialforge-config` creates the combined mode. Tests execute the client and
review code rather than trusting synthetic acceptance flags.

Full standalone SpatialForge backend/worker packaging and a fresh end-to-end
scene run are still outstanding. The release must not be labeled complete based
only on restored core files, UI startup or offline tests.

## Actual verification

- Windows: 15 core tests, 2 HTTP client tests and 12 real review-function tests
  passed. The four-image production demo produced a portable archive containing
  4 questions. A deep Windows path first hit MAX_PATH; the retained failure was
  reproduced successfully with a shorter workspace, documented in README.
- Linux: the committed source archive was extracted into a new directory and
  installed into a fresh Python 3.11 virtual environment. Core tests, production
  demo and adapter regressions passed from this installed package.
- Reused a built DSH with Node 22.22.2: setup generated the combined preset;
  the actual DSH tool factory registered 20 SpatialForge tools and 2 review hooks.
  Its catalog tool successfully read the existing live SpatialForge service.
- Started the repository launcher in an isolated DSH home on a spare local port:
  authenticated web GET returned HTML and HTTP 200, then the owned process group
  was stopped. The validation client needed cookies for DSH's token redirect;
  the first two client attempts failed without them and are not counted as passes.
- Model API calls, Isaac starts, scene submissions and shared-service restarts:
  zero. A fresh DSH dependency build and a new 3D scene were not tested.

Machine-readable evidence: [publication-20260930.json](validation/publication-20260930.json).
