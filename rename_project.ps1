# rename_project.ps1
# Run this from your "Strava Project" directory
# Usage: powershell -ExecutionPolicy Bypass -File rename_project.ps1

Write-Host "=== Cycling Segment Predictor - Project Rename ===" -ForegroundColor Cyan
Write-Host ""

# 1. Rename the main app file
if (Test-Path "Strava_app.py") {
    if (Test-Path "app.py") {
        Write-Host "WARNING: app.py already exists. Backing up to app.py.bak" -ForegroundColor Yellow
        Move-Item "app.py" "app.py.bak" -Force
    }
    Rename-Item "Strava_app.py" "app.py"
    Write-Host "OK Renamed Strava_app.py -> app.py" -ForegroundColor Green
} else {
    Write-Host "SKIP Strava_app.py not found (already renamed?)" -ForegroundColor Yellow
}

# 2. Rename the database
if (Test-Path "strava.db") {
    if (Test-Path "segments.db") {
        Write-Host "WARNING: segments.db already exists. Backing up to segments.db.bak" -ForegroundColor Yellow
        Move-Item "segments.db" "segments.db.bak" -Force
    }
    Copy-Item "strava.db" "segments.db"
    Write-Host "OK Copied strava.db -> segments.db (original kept as backup)" -ForegroundColor Green
} else {
    Write-Host "SKIP strava.db not found" -ForegroundColor Yellow
}

# 3. Update pipeline.py
if (Test-Path "pipeline.py") {
    (Get-Content "pipeline.py") -replace '"strava\.db"', '"segments.db"' -replace "'strava\.db'", "'segments.db'" | Set-Content "pipeline.py"
    Write-Host "OK Updated pipeline.py: strava.db -> segments.db" -ForegroundColor Green
}

# 4. Update scraperSel.py
if (Test-Path "scraperSel.py") {
    (Get-Content "scraperSel.py") -replace '"strava\.db"', '"segments.db"' -replace "'strava\.db'", "'segments.db'" | Set-Content "scraperSel.py"
    Write-Host "OK Updated scraperSel.py: strava.db -> segments.db" -ForegroundColor Green
}

# 5. Update config.py
if (Test-Path "config.py") {
    (Get-Content "config.py") -replace '"strava\.db"', '"segments.db"' -replace "'strava\.db'", "'segments.db'" -replace 'strava\.db', 'segments.db' | Set-Content "config.py"
    Write-Host "OK Updated config.py: strava.db -> segments.db" -ForegroundColor Green
}

# 6. Update test_system.py
if (Test-Path "test_system.py") {
    (Get-Content "test_system.py") -replace '"strava\.db"', '"segments.db"' -replace "'strava\.db'", "'segments.db'" -replace 'strava\.db', 'segments.db' | Set-Content "test_system.py"
    Write-Host "OK Updated test_system.py: strava.db -> segments.db" -ForegroundColor Green
}

# 7. Update STREAMLIT_GUIDE.md
if (Test-Path "STREAMLIT_GUIDE.md") {
    (Get-Content "STREAMLIT_GUIDE.md") -replace 'Strava_app\.py', 'app.py' -replace 'strava_app\.py', 'app.py' -replace 'strava\.db', 'segments.db' -replace 'Strava Segment', 'Cycling Segment' | Set-Content "STREAMLIT_GUIDE.md"
    Write-Host "OK Updated STREAMLIT_GUIDE.md" -ForegroundColor Green
}

# 8. Update README.md
if (Test-Path "README.md") {
    (Get-Content "README.md") -replace 'Strava_app\.py', 'app.py' -replace 'strava_app\.py', 'app.py' -replace 'strava\.db', 'segments.db' -replace 'Strava Segment Time Predictor', 'Cycling Segment Predictor' | Set-Content "README.md"
    Write-Host "OK Updated README.md" -ForegroundColor Green
}

# 9. Update Segment_Pull.py (if it references strava.db)
if (Test-Path "Segment_Pull.py") {
    (Get-Content "Segment_Pull.py") -replace '"strava\.db"', '"segments.db"' -replace "'strava\.db'", "'segments.db'" | Set-Content "Segment_Pull.py"
    Write-Host "OK Updated Segment_Pull.py: strava.db -> segments.db" -ForegroundColor Green
}

# 10. Update Fill_and_Clean_Elevation.py
if (Test-Path "Fill_and_Clean_Elevation.py") {
    (Get-Content "Fill_and_Clean_Elevation.py") -replace '"strava\.db"', '"segments.db"' -replace "'strava\.db'", "'segments.db'" | Set-Content "Fill_and_Clean_Elevation.py"
    Write-Host "OK Updated Fill_and_Clean_Elevation.py: strava.db -> segments.db" -ForegroundColor Green
}

# 11. Update flag_suspicious_segments.py
if (Test-Path "flag_suspicious_segments.py") {
    (Get-Content "flag_suspicious_segments.py") -replace '"strava\.db"', '"segments.db"' -replace "'strava\.db'", "'segments.db'" | Set-Content "flag_suspicious_segments.py"
    Write-Host "OK Updated flag_suspicious_segments.py: strava.db -> segments.db" -ForegroundColor Green
}

# 12. Update Verify_db.py
if (Test-Path "Verify_db.py") {
    (Get-Content "Verify_db.py") -replace '"strava\.db"', '"segments.db"' -replace "'strava\.db'", "'segments.db'" | Set-Content "Verify_db.py"
    Write-Host "OK Updated Verify_db.py: strava.db -> segments.db" -ForegroundColor Green
}

# 13. Update db.py
if (Test-Path "db.py") {
    (Get-Content "db.py") -replace '"strava\.db"', '"segments.db"' -replace "'strava\.db'", "'segments.db'" | Set-Content "db.py"
    Write-Host "OK Updated db.py: strava.db -> segments.db" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Rename complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Replace app.py with the new version from Claude outputs" -ForegroundColor White
Write-Host "  2. Replace sb_auth.py with the new version from Claude outputs" -ForegroundColor White
Write-Host "  3. Run: streamlit run app.py" -ForegroundColor White
Write-Host "  4. Verify everything works, then delete strava.db and Strava_app.py backups" -ForegroundColor White
Write-Host ""
Write-Host "The old strava.db is kept as a backup. segments.db is a copy." -ForegroundColor Yellow
Write-Host "requests.db will be created automatically on first run." -ForegroundColor Yellow
