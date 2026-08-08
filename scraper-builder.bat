@echo off
cd /d "%~dp0"

echo ========================================
echo Running Seraphim weekend scraper...
echo ========================================

python seraphim-weekend-scraper.py --stores-file "Stores.txt" --output "matches.json" --stores-file "Stores - fatpack.txt" --output "matches - fatpack.json" --stores-file "Stores - build.txt" --output "matches - build.json"

if errorlevel 1 (
    echo.
    echo ERROR: Scraper failed. Site generation will not run.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Scraper completed successfully.
echo Generating site...
echo ========================================

python generate_site.py --tab-label "single" --input "matches.json" --tab-label "fatpack" --input "matches - fatpack.json" --tab-label "build" --input "matches - build.json" --stores-file "Stores.txt" --stores-file "Stores - fatpack.txt" --stores-file "Stores - build.txt"

if errorlevel 1 (
    echo.
    echo ERROR: Site generation failed.
    pause
    exit /b 1
)

echo.
echo ========================================
echo DONE!
echo ========================================
pause