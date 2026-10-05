# 第三方许可与归属

词达人一键刷题（基于 Easy Cidaren 的修复版）保留上游项目的 GPLv3 许可。完整 GPLv3 正文见根目录 `LICENSE`。

## 上游项目

- [ularch/Easy_Cidaren](https://github.com/ularch/Easy_Cidaren)：本修复版基于此项目整理，原作者归属保留。
- [github123666/cidaren](https://github.com/github123666/cidaren)：上游 README 标明的原始项目。

修复版名称与维护工作不改变上游代码的版权归属。

## 主要运行组件

下表记录本项目使用的主要第三方组件。各组件原有版权声明和完整许可文本仍然适用，应随实际分发的组件一并保留。

| 组件 | 用途 | 许可 | 上游 |
| --- | --- | --- | --- |
| PyQt6 | Windows 图形界面 | GPLv3 | [Riverbank Computing](https://www.riverbankcomputing.com/software/pyqt/) |
| Qt 6 / PyQt6-Qt6 | Qt 运行库与平台插件 | LGPLv3，另有模块适用各自许可 | [Qt](https://www.qt.io/) |
| spaCy | 本地词形处理 | MIT | [Explosion/spaCy](https://github.com/explosion/spaCy) |
| en_core_web_sm 3.7.1 | 本地英语模型 | MIT | [spaCy 英语模型](https://spacy.io/models/en) |
| Requests | 网络请求 | Apache-2.0 | [psf/requests](https://github.com/psf/requests) |
| Brotli | 响应解压 | MIT | [google/brotli](https://github.com/google/brotli) |
| playsound | 提示音播放 | MIT | [TaylorSMarks/playsound](https://github.com/TaylorSMarks/playsound) |

模型的原始许可与数据来源说明分别位于 `en_core_web_sm/LICENSE` 和 `en_core_web_sm/LICENSES_SOURCES`，分发模型时保留这些文件。模型版本 3.7.1 适配 spaCy `>=3.7.2,<3.8.0`。

打包版还包含 Python 运行时及上述组件使用的传递依赖；这些依赖继续受各自的许可与版权声明约束。构建工具、引导程序及实际随包组件的许可文本亦应保留。

本次整理保留的第三方完整许可文本位于 `licenses/`；Python 运行时许可位于 `licenses/PYTHON-LICENSE.txt`。

## 未分发的工具

本修复版 Windows 发布包不包含上游目录中的第三方 Token 抓取 EXE、DLL 或其他外部抓取工具。用户使用自己的有效 Token 登录。
