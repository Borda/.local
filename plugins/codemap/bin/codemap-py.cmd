@echo off
rem codemap-py Windows launcher (plan §7.3/§7.4): probe an eligible CPython, run
rem the single Python entry. Windows never depends on Bash.
setlocal
set "HERE=%~dp0"
set "ENTRY=%HERE%..\scripts\codemap_py_entry.py"
set "PROBE=import sys;v=sys.version_info;raise SystemExit(0 if sys.implementation.name=='cpython' and v.major==3 and 11<=v.minor<15 else 127)"

rem CODEMAP_PYTHON is quoted as a single token so a path with spaces is not
rem split (F9); the multi-word `py -3` form is used only for the built-ins below.
if not defined CODEMAP_PYTHON goto :defaults
"%CODEMAP_PYTHON%" -c "%PROBE%" >nul 2>&1
if errorlevel 1 goto :nointerp
"%CODEMAP_PYTHON%" "%ENTRY%" %*
exit /b %errorlevel%

:defaults
py -3 -c "%PROBE%" >nul 2>&1
if not errorlevel 1 goto :run_py3
python.exe -c "%PROBE%" >nul 2>&1
if not errorlevel 1 goto :run_python
python3.exe -c "%PROBE%" >nul 2>&1
if not errorlevel 1 goto :run_python3
goto :nointerp

:run_py3
py -3 "%ENTRY%" %*
exit /b %errorlevel%

:run_python
python.exe "%ENTRY%" %*
exit /b %errorlevel%

:run_python3
python3.exe "%ENTRY%" %*
exit /b %errorlevel%

:nointerp
echo codemap-py: no eligible CPython ^>=3.11,^<3.15 interpreter ^(set CODEMAP_PYTHON^) 1>&2
exit /b 127
