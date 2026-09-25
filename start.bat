@echo off
cd /d "%~dp0"
if not exist data\dictionary.sqlite python scripts\build_dictionary.py
python server\app.py --open
