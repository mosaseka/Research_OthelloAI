@echo off
setlocal
pushd "%~dp0" || exit /b 1

set "NAME=%~n1"
if not defined NAME set "NAME=OthelloGUI"
if /I "%~1"=="--build-only" set "NAME=OthelloGUI"
if not defined JAVA_HOME if exist "C:\Program Files\Java\jdk-25\bin\jar.exe" set "JAVA_HOME=C:\Program Files\Java\jdk-25"
set "TOOLS="
if defined JAVA_HOME set "TOOLS=%JAVA_HOME%\bin\"

if /I not "%NAME%"=="OthelloGUI" goto :runJavaFile

set "CLASSES=%CD%\build\othello_gui\swing-classes"
set "DIST=%CD%\build\othello_gui\dist"
set "AI_DIR=%DIST%\original_final_48"
if not exist "%CLASSES%\." mkdir "%CLASSES%"
if errorlevel 1 goto :finish

echo [INFO] Compiling OthelloGUI with OthelloAI_final_48 ...
"%TOOLS%javac" --release 17 -encoding UTF-8 -d "%CLASSES%" Othello.java OthelloGUI.java "original_final_48\OthelloAI_final_48.java"
if errorlevel 1 goto :finish

if not exist "%AI_DIR%\resources\." mkdir "%AI_DIR%\resources"
if errorlevel 1 goto :finish
xcopy /E /I /Q /Y "original_final_48\resources" "%AI_DIR%\resources"
if errorlevel 1 goto :finish
copy /Y "original_final_48\LICENSE" "%AI_DIR%\LICENSE" >nul
if errorlevel 1 goto :finish
"%TOOLS%jar" --create --file "%DIST%\othello.jar" --main-class OthelloGUI -C "%CLASSES%" .
if errorlevel 1 goto :finish
echo [INFO] Created "%DIST%\othello.jar"
if /I "%~1"=="--build-only" goto :finish

echo [INFO] Running OthelloGUI ...
"%TOOLS%java" -jar "%DIST%\othello.jar"
goto :finish

:runJavaFile
if /I "%NAME%"=="OthelloAI_03" cd /d "%~dp0original_03"
set "SRC=%~1"
if /I "%~x1"=="" if exist "%NAME%.java" set "SRC=%NAME%.java"
echo [INFO] Compiling %SRC% ...
"%TOOLS%javac" -encoding UTF-8 -cp . "%SRC%"
if errorlevel 1 goto :finish

echo [INFO] Running %NAME% ...
"%TOOLS%java" -cp . %NAME%

:finish
set "RESULT=%ERRORLEVEL%"
popd
endlocal & exit /b %RESULT%
