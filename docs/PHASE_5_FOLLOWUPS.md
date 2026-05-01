# Phase 5 Follow-up Tasks

These items were identified as "next steps" at the completion of Phase 5 implementation. They are not blockers for Phase 6 but should be addressed before the V1 release.

1. **Frontend build integration** — Mount `console/dist` via FastAPI `StaticFiles` for production serving. Currently the frontend is served via `vite dev` only.
2. **E2E tests** — Add Playwright or Cypress tests covering: login → queue → case detail → approve learning; break-glass flow; timeout countdown visibility.
3. **Closer-specific golden sets** — Add Closer verdict scenarios to `tests/eval/golden_sets/` with expected decisions (MALICIOUS, BENIGN, INCONCLUSIVE, NEEDS_MORE_INFO).
4. **Full dependency install validation** — Run `uv sync` and `npm install` in `console/` to verify the build succeeds with the new `fastapi`/`uvicorn` deps and React toolchain.
