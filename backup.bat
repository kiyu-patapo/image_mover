@echo off
git add .
git commit -m "update %date% %time%"
git push origin main

echo.
echo ===================================
echo   Claris: Backup Success, Master!!
echo ===================================
pause