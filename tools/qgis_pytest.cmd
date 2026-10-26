@echo off
rem Tests im Python der QGIS-Installation (headless). Aufruf: tools\qgis_pytest.cmd [pytest-Argumente]
rem QGIS-Pfad über QGIS_ROOT anpassen, Standard: C:\Program Files\QGIS 3.44.15
rem Einmalig: "%QGIS_ROOT%\bin\python-qgis-ltr.bat" -m pip install --user pytest
setlocal
if "%QGIS_ROOT%"=="" set "QGIS_ROOT=C:\Program Files\QGIS 3.44.15"
set "QT_QPA_PLATFORM=offscreen"
pushd "%~dp0.."
call "%QGIS_ROOT%\bin\python-qgis-ltr.bat" -m pytest %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
