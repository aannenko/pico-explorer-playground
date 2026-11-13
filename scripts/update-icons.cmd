@echo off
setlocal
cd /d "%~dp0.."
set "out=src\pico\displays\shared\_icons_data.py"
set "python=src\.venv\Scripts\python.exe"
if not exist "%python%" set "python=python"
"%python%" src\tools\icons-to-p4.py --in src\assets --out "%out%"
set "exit_code=%errorlevel%"
rem Names each icon that differs from git's index, as diff lines: -old, +new.
if %exit_code%==0 for /f %%n in ('git --no-pager diff --no-color --no-ext-diff -U0 -- "%out%" ^| findstr /r /c:"^-[A-Z]" /c:"^+[A-Z]"') do echo %%n
pause
exit /b %exit_code%
