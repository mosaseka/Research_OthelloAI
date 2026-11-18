@echo off
setlocal

if "%~1"=="" (
  echo Usage: run ^<JavaFile.java or ClassName^>
  exit /b 1
)

REM 引数から基本名と拡張子を取得
set "NAME=%~n1"
set "SRC=%~1"

REM .java を省略している場合は補完
if /I "%~x1"=="" if exist "%NAME%.java" set "SRC=%NAME%.java"

REM JavaFX SDK の場所（必要なら変更）
set "FX=C:\Program Files\Java\javafx-sdk-25\lib"
set "MODS=javafx.controls"

echo [INFO] Compiling %SRC% ...
if /I "%NAME%"=="OthelloGUI" (
  javac -cp . --module-path "%FX%" --add-modules %MODS% Othello.java OthelloAI_03.java OthelloGUI.java
) else (
  javac -cp . --module-path "%FX%" --add-modules %MODS% "%SRC%"
)
if errorlevel 1 exit /b %errorlevel%

echo [INFO] Running %NAME% ...
java --enable-native-access=ALL-UNNAMED --module-path "%FX%" --add-modules %MODS% -cp . %NAME%

endlocal
