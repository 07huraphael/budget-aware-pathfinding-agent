$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    python -u run.py study
    if ($LASTEXITCODE -ne 0) { throw 'Study failed. Check the output above.' }
}
finally {
    Pop-Location
}
