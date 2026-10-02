param([switch]$MigrationRoundTrip)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Avval scripts/local.ps1 setup ni bajaring.' }
& $python scripts/local_db.py start
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL ishga tushmadi.' }
if (-not $env:TEST_DATABASE_URL) {
    $env:TEST_DATABASE_URL = & $python -c "from dotenv import dotenv_values; from sqlalchemy.engine import make_url; print(make_url(dotenv_values('.env')['DATABASE_URL']).set(database='crm_test').render_as_string(hide_password=False))"
    if ($LASTEXITCODE -ne 0) { throw 'Test bazasi sozlanmadi.' }
}
& $python -c "import os; from sqlalchemy.engine import make_url; assert make_url(os.environ['TEST_DATABASE_URL']).database.endswith('_test'), 'Dedicated _test database required'"
if ($LASTEXITCODE -ne 0) { throw 'Alohida _test bazasi talab qilinadi.' }
$env:DATABASE_URL = $env:TEST_DATABASE_URL
$env:JWT_SECRET = 'local-test-secret-only-not-for-production-123456'
& $python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Test kutubxonalari o''rnatilmadi.' }
& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
if ($MigrationRoundTrip) {
    & $python -m alembic downgrade base
    if ($LASTEXITCODE -ne 0) { throw 'Migration downgrade failed' }
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Migration re-upgrade failed' }
}
& $python -m alembic check
if ($LASTEXITCODE -ne 0) { throw 'Model/migration drift detected' }
& $python -m ruff check app tests main.py alembic scripts/local_db.py
if ($LASTEXITCODE -ne 0) { throw 'Lint failed' }
& $python -m ruff format --check app tests main.py alembic scripts/local_db.py
if ($LASTEXITCODE -ne 0) { throw 'Format check failed' }
& $python -m pytest --cov=app --cov-report=term-missing --cov-report=html --junitxml=.local/test-results.xml
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
