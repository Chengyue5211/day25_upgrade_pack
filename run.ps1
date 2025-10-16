
param([int]$Port=8000)
$env:UPG25_DB = if ($env:UPG25_DB) { $env:UPG25_DB } else { "upgrade25.sqlite3" }
uvicorn app.main:app --reload --port $Port
