# StaffOS 仓库结构（项目级平铺）

> 2026-09-23 仓库重组后的权威结构说明。历史命名（qwenpaw 包名、CLI 命令、
> QWENPAW_* 环境变量、页面标题等）按既定计划后续逐步替换，目录结构先行统一。

## 一、顶层结构

```
QwenPaw/                                # 仓库根
├── staffos-server/                     # 服务端项目（Python，自包含）
│   ├── src/qwenpaw/                    #   源码（src-layout；包名后续再改）
│   ├── packages/qwenpawmail-mcp/       #   随包分发的邮件 MCP Server
│   ├── tests/                          #   Python 测试（unit/contract/integration/eval）
│   ├── db/                             #   SQL 变更管理（dev/feature 分支映射规范不变，
│   │                                   #   仅路径前缀变为 staffos-server/db/...）
│   ├── scripts/                        #   wheel 打包、run_tests、migrate 等服务端脚本
│   ├── pyproject.toml  setup.py  Makefile  .flake8  .python-version
│   └── .venv/                          #   本机虚拟环境（不进 git，在 staffos-server 下重建）
├── staffos-console/                    # 管理控制台前端（自包含）
│   ├── src/  src-tauri/                #   src-tauri 为 Tauri 桌面端壳
│   ├── scripts/pack-tauri/  scripts/pack/   # 桌面安装包打包脚本（PyInstaller/Tauri/NSIS）
│   └── package.json
├── staffos-work/                       # 企业员工端前端（原 xianwork，自包含）
├── staffos-website/                    # 官网/文档站（自包含）
├── staffos-e2e/                        # Playwright E2E 测试框架（自包含）
├── plugins/                            # 插件生态（apps/channel/tool/bundle，原位）
├── deploy/                             # 工程级部署编排（多阶段 Dockerfile：跨项目构建）
├── docker-compose.yml                  # 工程级容器编排
├── scripts/                            # 工程级脚本（install.*、docker_build、restart_backend）
│   └── pack/                           #   插件元数据打包（generate_plugin_metadata 等 4 个，
│                                       #   供 plugins-release/release CI 使用）
├── docs/                               # 工程文档（本文件）
└── .github/                            # CI/CD
```

## 二、分区语义

| 分区 | 语义 |
| --- | --- |
| `staffos-server` `staffos-console` `staffos-work` `staffos-website` `staffos-e2e` | 五个自包含项目：各自管理依赖、构建、测试 |
| `plugins` | 插件生态集合（非单一项目） |
| `deploy` `docker-compose.yml` `scripts/pack` | 工程级交付设施（跨项目编排） |
| `docs` `.github` | 工程治理 |

## 三、构建产物注入链（跨项目，改动时必须同步）

后端包内置三份前端产物，打包与源码运行都依赖以下注入方向：

| 源（构建产物） | 目标（后端包内） | 执行者 |
| --- | --- | --- |
| `staffos-console/dist/` | `staffos-server/src/qwenpaw/console/` | `staffos-server/scripts/wheel_build.sh\|.ps1`、`scripts/install.sh`、`deploy/Dockerfile` |
| `staffos-work/dist/` | `staffos-server/src/qwenpaw/xianwork/` | `deploy/Dockerfile` |
| `staffos-website/public/docs/` | `staffos-server/src/qwenpaw/docs/` | `wheel_build`、`install.sh`、`deploy/Dockerfile` |

注入目标已在 `.gitignore`（`staffos-server/src/qwenpaw/console|docs`）与
`pyproject.toml` package-data 中声明。

## 四、各项目开发命令速查

| 动作 | 目录 | 命令 |
| --- | --- | --- |
| 后端环境重建 | 仓库根 | `cd staffos-server; uv venv; uv pip install -e ".[test,pg]"` |
| 启动后端 | `staffos-server` | `.venv\Scripts\qwenpaw.exe app`（默认 8188，`QWENPAW_PORT` 可覆盖） |
| 后端单测 | `staffos-server` | `.venv\Scripts\python.exe -m pytest tests/unit -q` 或 `make quick` |
| 控制台前端 dev | `staffos-console` | `npm run dev`（5173，/api 代理到后端） |
| 控制台前端 build | `staffos-console` | `npm run build` |
| 桌面端打包 | `staffos-console` | `scripts/pack-tauri/build_win_pyinstaller.ps1` 等 |
| 员工端 dev | `staffos-work` | `npm run dev`（5174，/api 代理到后端） |
| 官网 build | `staffos-website` | `npm run build` 或 `scripts/website_build.sh` |
| E2E 测试 | `staffos-e2e` | `scripts/start_test_server.sh --bg` 后 `pytest tests/` |
| Docker 镜像 | 仓库根 | `bash scripts/docker_build.sh [TAG]` |
| 一键重启后端 | 仓库根 | `scripts/restart_backend.bat`（已指向 staffos-server） |

## 五、历史变更记录

- 2026-09-23：项目级平铺重组（本文件所述结构）。原 `console/ xianwork/ website/ e2e/`
  与根下 Python 资产（`src/ tests/ db/ packages/ pyproject.toml` 等）按上述映射迁移；
  内部品牌命名（qwenpaw → staffos）留待后续专项替换。
- 2026-09-23：`staffos-portal` 更名为 `staffos-work`（目录、`deploy/Dockerfile`
  与本文件引用同步）。
