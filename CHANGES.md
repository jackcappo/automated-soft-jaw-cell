# Changes in this drop (v0.2.0)

Copy these files over your repo, then **delete** the files listed at the bottom.

## Added
- `softjaw/` Python package: geometry kernel, jaw generator + validation, CAM exporters,
  B601-DM kinematics, cell planner, cell controller with fault injection, CLI.
- `tests/` 25 automated tests. `tools/` example generator, machine-model importer,
  simulator bundler, headless simulator test.
- `examples/parts/` 7 test parts (5 that need soft jaws, 2 that must be rejected);
  `config/jobs/` one job per part.
- New profiles: `config/blanks/`, `config/grippers/`, `config/robots/`, `config/cells/`.
- `docs/DESIGN-DECISIONS.md`, `docs/MEASUREMENTS.md`, `CHANGES.md`, `requirements.txt`.

## Changed
- `sim-web/` rewritten: replays planner paths and controller logs; right-handed scene with
  correct URDF rotations (the old one swapped axis order and was mirrored); Babylon.js from
  a pinned CDN (the old `vendor/babylon.js` was never committed, so the page could not start);
  optional detailed machine model.
- Vise, machine, CAM profiles: every fit-critical value now carries a status
  (published / measured / assumed / estimated).
- `README.md`, `docs/vevor-vise-measurement-sheet.md`, `sim-web/*.md`, `.gitignore`.

## Unchanged
- `docs/PRD.md` (amendments are in `docs/DESIGN-DECISIONS.md`).

## Delete
- `config/example-job.json` (replaced by `config/jobs/*.json`).
