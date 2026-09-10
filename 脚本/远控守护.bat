@echo off
rem 远控服务守护: 服务退出/崩溃后 5 秒自动拉起 (由 安装远控服务.bat 注册)
cd /d "%~dp0.."
set 远控_无暂停=1
:loop
call "%~dp0启动远控.bat"
echo [守护] 远控服务已退出, 5 秒后自动重启 (Ctrl+C 终止守护)...
timeout /t 5 /nobreak >nul
goto loop
