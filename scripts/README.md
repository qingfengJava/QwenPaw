# Scripts

Run from **repo root**.

## Build wheel (with latest console)

```bash
bash staffos-server/scripts/wheel_build.sh
```

- Builds the console frontend (`staffos-console/`), copies `staffos-console/dist` to `staffos-server/src/qwenpaw/console/`, then builds the wheel. Output: `staffos-server/dist/*.whl`.

## Build website

```bash
bash staffos-website/scripts/website_build.sh
```

- Installs dependencies (pnpm or npm) and runs the Vite build. Output: `staffos-website/dist/`.

## Build Docker image

```bash
bash scripts/docker_build.sh [IMAGE_TAG] [EXTRA_ARGS...]
```

- Default tag: `qwenpaw:latest`. Uses `deploy/Dockerfile` (multi-stage: builds console then Python app).
- Example: `bash scripts/docker_build.sh myreg/qwenpaw:v1 --no-cache`.

## Run Test

```bash
# Run all tests
python scripts/run_tests.py

# Run all unit tests
python scripts/run_tests.py -u

# Run unit tests for a specific module
python scripts/run_tests.py -u providers

# Run integration tests
python scripts/run_tests.py -i

# Run all tests and generate a coverage report
python scripts/run_tests.py -a -c

# Run tests in parallel (requires pytest-xdist)
python scripts/run_tests.py -p

# Show help
python scripts/run_tests.py -h
```