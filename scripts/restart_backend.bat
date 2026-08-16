@echo off
chcp 65001 >nul
setlocal

REM 一键重启 QwenPaw 后端：让项目根目录 .env（QWENPAW_STORAGE_BACKEND=pg）生效。
REM 请在自己的终端/资源管理器中运行（不要在 IDE 沙箱里跑，沙箱无权限杀旧进程）。

REM 无论从哪里调用，都先切到项目根目录
cd /d "%~dp0.."

echo [1/3] 查找并终止 8088 / 8089 端口上的旧后端进程 ...

REM 按端口找 PID（PID 会变化，不写死），只处理 LISTENING 状态
for %%p in (8088 8089) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr "LISTENING"') do (
        echo     终止 PID %%a ^(端口 %%p^) ...
        taskkill /F /PID %%a >nul 2>&1
    )
)

echo [2/3] 等待端口释放 ...
timeout /t 2 /nobreak >nul

echo [3/3] 启动后端 http://127.0.0.1:8088 （存储后端按 .env 加载：pg）...
echo       看到日志中出现 "Created PostgreSQL engine" 即表示 PG 模式生效。
echo       此窗口保持打开可查看日志，关闭窗口即停止服务。

REM 前台启动，日志直接可见，Ctrl+C 可停止
".venv\Scripts\qwenpaw.exe" app
