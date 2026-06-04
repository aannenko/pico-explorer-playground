@echo off
REM Regenerates src\pico\icons_symbols.rgb332 from src\assets\icons_symbols.png
REM using the upstream Pimoroni spritesheet-to-rgb332.py converter.

setlocal
set "ROOT=%~dp0.."
set "SRC_PNG=%ROOT%\assets\icons_symbols.png"
set "TMP_OUT=%ROOT%\assets\icons_symbols.rgb332"
set "DEST=%ROOT%\pico\icons_symbols.rgb332"

python "%~dp0spritesheet-to-rgb332.py" "%SRC_PNG%" || exit /b 1
move /Y "%TMP_OUT%" "%DEST%" >nul || exit /b 1
echo Regenerated: %DEST%
endlocal
