@echo off
rem Tests im Python der QGIS-Installation (headless).
rem Aufruf: tools\qgis_pytest.cmd [3|4] [pytest-Argumente]
rem   ohne 3 oder 4: beide Versionen nacheinander, am Ende das Ergebnis je Version
rem   3 = QGIS 3.44 LTR (python-qgis-ltr.bat), 4 = QGIS 4 (python-qgis.bat)
rem Ordner über QGIS3_ROOT und QGIS4_ROOT anpassen, Standard: C:\Program Files\QGIS 3.44.15 und ...\QGIS 4.2.3
rem Einmalig je Version: "%QGIS_ROOT%\bin\python-qgis(-ltr).bat" -m pip install --user pytest
setlocal
if "%QGIS3_ROOT%"=="" set "QGIS3_ROOT=C:\Program Files\QGIS 3.44.15"
if "%QGIS4_ROOT%"=="" set "QGIS4_ROOT=C:\Program Files\QGIS 4.2.3"
set "QT_QPA_PLATFORM=offscreen"
pushd "%~dp0.."
if "%~1"=="3" goto only3
if "%~1"=="4" goto only4
set "RC3=0"
set "RC4=0"
call "%QGIS3_ROOT%\bin\python-qgis-ltr.bat" -m pytest %*
set "RC3=%ERRORLEVEL%"
call "%QGIS4_ROOT%\bin\python-qgis.bat" -m pytest %*
set "RC4=%ERRORLEVEL%"
echo.
if "%RC3%"=="0" (echo QGIS 3.44: alle Tests gruen) else (echo QGIS 3.44: FEHLGESCHLAGEN, Rueckgabewert %RC3%)
if "%RC4%"=="0" (echo QGIS 4:    alle Tests gruen) else (echo QGIS 4:    FEHLGESCHLAGEN, Rueckgabewert %RC4%)
popd
if not "%RC3%"=="0" exit /b %RC3%
exit /b %RC4%

:only3
shift
call "%QGIS3_ROOT%\bin\python-qgis-ltr.bat" -m pytest %1 %2 %3 %4 %5 %6 %7 %8 %9
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:only4
shift
call "%QGIS4_ROOT%\bin\python-qgis.bat" -m pytest %1 %2 %3 %4 %5 %6 %7 %8 %9
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
