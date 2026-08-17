"""启动 QwenPaw 后端服务"""
import os
import sys

# 切换到项目根目录
project_root = "d:\\IDEA版java相关知识学习\\37-openAi开发\\AI案例\\QwenPaw"
os.chdir(project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "qwenpaw.app._app:app",
        host="0.0.0.0",
        port=8088,
        reload=True,
        reload_dirs=[os.path.join(project_root, "src", "qwenpaw")],
    )