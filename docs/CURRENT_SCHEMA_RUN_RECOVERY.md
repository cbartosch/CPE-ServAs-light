# Current-schema Digital Twin run recovery

A structured 409 reporting mixed planning regions or an incompatible run schema is a fail-closed protection. Do not disable the gate and do not edit an immutable run in place.

From the repository root on Windows:

```powershell
.\scripts\Repair-LPR-CurrentSchemaRun.ps1 -Homes 500 -Profile smoke -Seed 2401
```

On macOS/Linux:

```sh
./scripts/repair-current-schema-run.sh --homes 500 --profile smoke --seed 2401
```

A successful result contains:

```text
status: PASS
new_run_created: true
active_pointer_moved: true
run_schema_version: lpr-digital-twin-run-v3-execution-economics
schema_is_current: true
quality_passed: true
legacy_run_mutation: false
```

After the smoke run passes, generate the intended footprint and select a case belonging to the new run. An already-open browser case remains associated with its original run.
