# SpatialForge integration

`plugin/tools.mjs` contains the production tool definitions and the delivery
review hooks, adapted to a configured DSH root, service URL and token environment
variable. No private host paths or tokens are embedded. `build_preset.py` combines
them with BenchForge in a separate **BenchForgeV2** preset.

## Existing service connection

Run DSH on the SpatialForge service machine: returned evidence paths are local
to that machine. Configure the service's existing Windows desktop worker and use
its single Isaac queue. This client never starts another worker or simulator.

Copy `config.example.json` to a private `spatialforge.local.json`. Set
`SPATIALFORGE_OPERATOR_TOKEN` in the environment used to launch DSH, then:

```bash
python integrations/spatialforge/cli.py status --config spatialforge.local.json
python integrations/spatialforge/cli.py status --config spatialforge.local.json --run-id sf_YOUR_RUN
python benchforge.py setup --spatialforge-config spatialforge.local.json
python benchforge.py start
```

Without a run ID, status calls authenticated `POST /catalog`; with an ID it calls
`POST /observe`. SpatialForge has no run-status `GET /status` endpoint.
Missing config or credentials fails with an actionable error.

## Test the code without production jobs

```bash
python integrations/spatialforge/smoke.py
```

Python uses a local HTTP server to verify the request contract. Node replays
the actual review functions, including failed physics, missing image visibility,
reference/render attachments and broken delivery links. The former fixture that
simply asserted `success=true` and `loadable=true` has been removed.

## Remaining release work

The standalone SpatialForge service, PostgreSQL/BenchClaw dependencies, generation
workers and desktop installation are not yet packaged here. A configured existing
service is required. Full from-scratch scene production remains an open release
requirement; client tests and the BenchForge UI do not establish it.
