# Vendored wheels

Drop `.whl` files here and both images install from them with `--no-index`,
never contacting PyPI. This is the reliable path on a network that blocks or
intercepts the package index.

Populate from a machine where pip works:

    ./scripts/vendor-wheels.sh          # macOS / Linux / WSL
    .\scripts\vendor-wheels.ps1         # Windows PowerShell

The directory ships empty, so the build falls back to the index when unused.
