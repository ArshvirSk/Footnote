# start.ps1 — native startup, no Docker (DB is Neon; see .env)
$ErrorActionPreference = "Stop"

Write-Host "Checking for Python virtual environment..." -ForegroundColor Green
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
.venv\Scripts\Activate.ps1

Write-Host "Installing Python dependencies..." -ForegroundColor Green
pip install -r services/api/requirements.txt
pip install -r services/workers/requirements.txt

if (-not (Test-Path ".env")) {
    Write-Host "No .env found — copy .env.example to .env and set DATABASE_URL / DATABASE_URL_SYNC (Neon)." -ForegroundColor Red
    exit 1
}

Write-Host "Applying database migrations (idempotent)..." -ForegroundColor Green
$env:PYTHONPATH = "."
python -m services.api.scripts.migrate
if ($LASTEXITCODE -ne 0) { Write-Host "Migration failed." -ForegroundColor Red; exit 1 }

Write-Host "Installing Node.js dependencies..." -ForegroundColor Green
Push-Location apps/web
npm install
Pop-Location

Write-Host "Starting API, Worker, and Web UI in separate windows..." -ForegroundColor Green
# Workers (API/worker/web) run natively; Redis must be reachable at REDIS_URL for the Arq worker.
Start-Process -NoNewWindow -FilePath "powershell" -ArgumentList "-NoExit -Command `"cd apps/web; npm run dev`""
Start-Process -NoNewWindow -FilePath "powershell" -ArgumentList "-NoExit -Command `"cd $PWD; .venv\Scripts\Activate.ps1; `$env:PYTHONPATH='.'; uvicorn services.api.app.main:app --reload --port 8000`""
Start-Process -NoNewWindow -FilePath "powershell" -ArgumentList "-NoExit -Command `"cd $PWD; .venv\Scripts\Activate.ps1; `$env:PYTHONPATH='.'; arq services.workers.app.worker.WorkerSettings`""

Write-Host "All services started! Check the terminal windows for logs." -ForegroundColor Cyan
Write-Host "Web UI: http://localhost:3000/ops"
Write-Host "API:    http://localhost:8000/docs"
