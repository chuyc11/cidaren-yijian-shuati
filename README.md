# Easy Cidaren 修复版

基于 [ularch/Easy_Cidaren](https://github.com/ularch/Easy_Cidaren) 的修复版本，保留原项目及 [github123666/cidaren](https://github.com/github123666/cidaren) 的归属。本仓库按 GPLv3 发布，完整许可见 [LICENSE](LICENSE)。

## 下载与运行

- [直接下载 Windows x64 压缩包](https://github.com/chuyc11/Easy-Cidaren-Fixed/releases/download/v2026.10.06/Easy_Cidaren_Fixed-windows-x64.zip)
- [查看 v2026.10.06 发布说明](https://github.com/chuyc11/Easy-Cidaren-Fixed/releases/tag/v2026.10.06)

Windows 打包版无需安装 Python。

1. 下载 `Easy_Cidaren_Fixed-windows-x64.zip`，将整个压缩包解压到可写文件夹。
2. 打开解压后的文件夹，双击 `Easy_Cidaren_Fixed.exe`。请保留同目录中的配置、模型、资源及运行依赖，不要单独移动 EXE。
3. 在程序中填写你自己的用户 Token，点击登录，再选择自己的任务。

发布包不包含任何用户的 Token、API Key、账号任务记录或原始日志，也不附带第三方 Token 抓取工具。请自行准备自己的有效 Token；Token 失效后需要更新。

## 配置

基础配置位于 `config/config.json`，可通过程序设置页面调整。程序需要该配置文件，请保留解压包内的 `config` 目录。任务恢复数据、学习缓存及日志在使用时由程序生成，属于当前使用者的数据。

AI 配置是可选项：

1. 将 `config/ai_config.example.json` 复制为 `config/ai_config.json`。
2. 填写你自己的 `base_url`、`api_key` 和 `model`。
3. 重启程序使配置生效。

未配置 AI 时，程序使用本地规则与模型。不要将填写了 API Key 的配置文件上传到仓库或分享给他人。

## 本版修复

- 修复班级测试流程中的任务处理问题，完善异常恢复与完成状态同步。
- 支持断点续作，重新读取当前任务状态后恢复进度。
- 复用词形模型、词表缓存及后台处理，减少重复工作与界面等待。
- 无法可靠确定答案时停止，并提示需要处理的问题。
- 按账号隔离恢复数据与任务记录，减少切换账号时的数据混用。

详细变更见 [CHANGELOG.md](CHANGELOG.md)。测试验证结果以对应 Release 的发布说明为准。

## 从源码运行

源码运行需要 Python 3.12，并保留仓库中的 `config`、`assets`、`en_core_web_sm` 等资源目录。

```powershell
python -m pip install -r requirements.txt
python main.py
```

`requirements.txt` 提供主程序的核心依赖。Windows 打包版用户无需执行这些命令。

验证源码与重建 Windows 包：

```powershell
python -m unittest discover -s tests -p "test*.py" -q
python main.py --self-test --self-test-report smoke-report.json
powershell -ExecutionPolicy Bypass -File packaging/build.ps1
```

此版本已通过 166 项离线回归测试。自检检查图形界面、本地词形模型和配置/恢复记录保存；不会登录或执行线上任务。打包产物位于 `dist/Easy_Cidaren_Fixed/`。

## 许可与归属

本修复版继续采用 GPLv3。上游项目说明由仓库中的上游归属文档保留；修复版变更与使用说明以本 README 和 CHANGELOG 为准。

本地英语模型与第三方运行库的许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 及各组件随附的许可文本。分发时应保留项目许可、上游归属和第三方许可。

完整第三方许可文本收录在 `licenses/`，上游原说明保留在 [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)。
