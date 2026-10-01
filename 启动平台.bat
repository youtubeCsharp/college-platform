@echo off
chcp 65001 >nul
cd /d %~dp0
title 数字经济与管理学院综合管理平台
python app.py
pause
