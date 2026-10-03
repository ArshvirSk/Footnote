# start.ps1
Write-Host "Starting Footnote Databases (Postgres & Redis)..." -ForegroundColor Green
docker compose up -d

Write-Host "Checking for Python virtual environment..." -ForegroundColor Green
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
.venv\Scripts\Activate.ps1

Write-Host "Installing Python dependencies..." -ForegroundColor Green
pip install -r services/api/requirements.txt
pip install -r services/workers/requirements.txt

Write-Host "Installing Node.js dependencies..." -ForegroundColor Green
Push-Location apps/web
npm install
Pop-Location

# Seed the database (since we wiped the docker volumes)
Write-Host "Seeding the database..." -ForegroundColor Green
Get-Content db\seed.sql | docker compose exec -T db psql -U postgres -d footnote

Write-Host "Starting API, Worker, and Web UI concurrently..." -ForegroundColor Green
# We use Start-Process to open them in separate terminal windows so you can see their logs
Start-Process -NoNewWindow -FilePath "powershell" -ArgumentList "-NoExit -Command `"cd apps/web; npm run dev`""
Start-Process -NoNewWindow -FilePath "powershell" -ArgumentList "-NoExit -Command `".venv\Scripts\Activate.ps1; set PYTHONPATH=.; uvicorn services.api.app.main:app --reload --port 8000`""
Start-Process -NoNewWindow -FilePath "powershell" -ArgumentList "-NoExit -Command `".venv\Scripts\Activate.ps1; set PYTHONPATH=.; arq services.workers.app.worker.WorkerSettings`""

Write-Host "All services started natively! Check the terminal windows for logs." -ForegroundColor Cyan
Write-Host "Web UI: http://localhost:3000/ops"
Write-Host "API: http://localhost:8000/docs"
