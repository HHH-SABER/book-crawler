@echo off
rem 注册/卸载 远控服务开机自启 - 免管理员: 放入用户启动文件夹
setlocal
set "启动夹=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if /i "%~1"=="卸载" (
    del "%启动夹%\远控服务.bat" 2>nul
    echo 已卸载。
    pause
    exit /b 0
)
copy /y "%~dp0远控守护.bat" "%启动夹%\远控服务.bat" >nul
if errorlevel 1 (
    echo [ERROR] 复制到启动文件夹失败
) else (
    echo 已注册: 登录后自动启动远控服务 - 含崩溃自动拉起
    echo 卸载请运行: %~nx0 卸载
)
pause
