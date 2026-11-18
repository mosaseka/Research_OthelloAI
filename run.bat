@echo off
setlocal
pushd "%~dp0" || exit /b 1

set "NAME=%~n1"
if not defined NAME set "NAME=OthelloGUI"
set "FX=C:\Program Files\Java\javafx-sdk-25\lib"
set "MODS=javafx.controls"

if /I not "%NAME%"=="OthelloGUI" goto :runJavaFile

set "CLASSES=%CD%\build\othello_gui"
if not exist "%CLASSES%\." mkdir "%CLASSES%"
if not exist "%CLASSES%\." goto :finish

echo [INFO] Compiling OthelloGUI with OthelloAI_final_48 ...
javac -encoding UTF-8 -d "%CLASSES%" --module-path "%FX%" --add-modules %MODS% Othello.java OthelloGUI.java "original_final_48\OthelloAI_final_48.java"
if errorlevel 1 goto :finish

echo [INFO] Running OthelloGUI ...
java --enable-native-access=javafx.graphics,ALL-UNNAMED --module-path "%FX%" --add-modules %MODS% -cp "%CLASSES%" OthelloGUI
goto :finish

:runJavaFile
if /I "%NAME%"=="OthelloAI_03" cd /d "%~dp0original_03"
set "SRC=%~1"
if /I "%~x1"=="" if exist "%NAME%.java" set "SRC=%NAME%.java"
echo [INFO] Compiling %SRC% ...
javac -encoding UTF-8 -cp . --module-path "%FX%" --add-modules %MODS% "%SRC%"
if errorlevel 1 goto :finish

echo [INFO] Running %NAME% ...
java --enable-native-access=javafx.graphics,ALL-UNNAMED --module-path "%FX%" --add-modules %MODS% -cp . %NAME%

:finish
set "RESULT=%ERRORLEVEL%"
popd
endlocal & exit /b %RESULT%
