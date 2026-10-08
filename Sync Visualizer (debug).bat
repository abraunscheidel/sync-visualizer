@echo off
rem Same as "Sync Visualizer.bat" but with the Debug menu (simulate slow decoding, live status).
setlocal
set "SYNCVIZ_DEBUG=1"
call "%~dp0Sync Visualizer.bat" %*
