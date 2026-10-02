param([switch]$CreateDatabase, [switch]$GenerateMigration, [switch]$MigrationRoundTrip, [switch]$StopDatabase)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$runtimePython = 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$projectRoot\.packages;$projectRoot"
$env:TEST_DATABASE_URL = 'postgresql+psycopg://crm_test@127.0.0.1:55432/crm_test'
$env:DATABASE_URL = $env:TEST_DATABASE_URL
$env:JWT_SECRET = 'local-test-secret-only-not-for-production-123456'
if ($StopDatabase) {
    & .local\pgsql\bin\pg_ctl.exe -D .local\pgdata -m fast -w stop
    exit $LASTEXITCODE
}
if ($CreateDatabase) {
    & .local\pgsql\bin\createdb.exe -h 127.0.0.1 -p 55432 -U crm_test crm_test
    if ($LASTEXITCODE -ne 0) { throw 'Database creation failed' }
}
if ($GenerateMigration) {
    & $runtimePython -m alembic revision --autogenerate -m 'Initial CRM schema'
    if ($LASTEXITCODE -ne 0) { throw 'Migration generation failed' }
}
& $runtimePython -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
if ($MigrationRoundTrip) {
    & $runtimePython -m alembic downgrade base
    if ($LASTEXITCODE -ne 0) { throw 'Migration downgrade failed' }
    & $runtimePython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Migration re-upgrade failed' }
}
& $runtimePython -m alembic check
if ($LASTEXITCODE -ne 0) { throw 'Model/migration drift detected' }
& $runtimePython -m ruff check app tests main.py alembic --fix
if ($LASTEXITCODE -ne 0) { throw 'Lint failed' }
& $runtimePython -m ruff format app tests main.py alembic
& $runtimePython -m pytest --cov=app --cov-report=term-missing --cov-report=html --junitxml=.local/test-results.xml
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $runtimePython -c "from app.main import app; schema=app.openapi(); print('API operations:', sum(1 for path in schema['paths'].values() for method in path if method in ['get','post','put','patch','delete'])); import json; from pathlib import Path; Path('docs/openapi.json').write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding='utf-8')"
