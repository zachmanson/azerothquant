@echo off
rem Starts a fresh `brain watch` in its own window, then the Battle.net app.
rem Launch the game from this instead of Battle.net and every in-game Reload is
rem imported on its own; a second Reload then loads the new Recommendations.
rem
rem Any watcher from an earlier run is stopped first: a long-running one keeps
rem writing Recommendations with the Brain code it started with.

set BATTLENET=Z:\Battle.net\Battle.net Launcher.exe

taskkill /FI "WINDOWTITLE eq brain watch*" >nul 2>&1
start "brain watch" /D "%~dp0..\brain" "%~dp0..\.venv\Scripts\brain.exe" watch
start "" "%BATTLENET%"
