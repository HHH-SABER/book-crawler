@echo off
rem 注册/卸载 远控服务开机自启 (登录时启动, 无需管理员)
rem   安装: 双击本脚本
rem   卸载: 本脚本加参数 卸载
setlocal
set "任务名=小说爬虫远控"
if /i "%~1"=="卸载" (
    schtasks /Delete /TN "%任务名%" /F
    echo 已卸载。
    pause
    exit /b 0
)
schtasks /Create /TN "%任务名%" /SC ONLOGON /TR "\"%~dp0远控守护.bat\"" /F
if errorlevel 1 (
    echo [ERROR] 注册失败。可改用"任务计划程序"手动创建: 触发器=登录时, 操作=%~dp0远控守护.bat
) else (
    echo 已注册: 登录后自动启动远控服务 (含崩溃自动拉起)。
    echo 卸载请运行: %~nx0 卸载
)
echo.
echo 提示: 手机访问前先确认 数据/远控配置.json 的 绑定 与 外链前缀
echo       (详见 文档/手机远控方案设计.md 使用指南)
pause
