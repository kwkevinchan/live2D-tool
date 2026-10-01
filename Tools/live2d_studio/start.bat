@echo off
rem Live 2D 工作室 -> http://127.0.0.1:7861
rem 用 PATH 上的 python（要有 numpy、scipy、Pillow、opencv、gradio）；環境變數 LIVE2D_PYTHON 可以指定另一個
cd /d %~dp0\..\..
if "%LIVE2D_PYTHON%"=="" set LIVE2D_PYTHON=python
"%LIVE2D_PYTHON%" Tools\live2d_studio\app.py
