@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 挂件需要 tkinter，托管版 Python 没带，用系统 Python
set PYTHONW=D:\python310\pythonw.exe
if not exist "%PYTHONW%" set PYTHONW=pythonw

rem 走 run_widget.py 而不是 -m，避免依赖工作目录
start "" "%PYTHONW%" "%~dp0run_widget.py"
