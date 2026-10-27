# 开发、测试与打包

## 开发环境

在 Windows PowerShell 中，从项目根目录执行以下命令。推荐 Python 3.12，开发依赖中已固定本项目使用的 `keyboard` 和 PyInstaller 版本。

```powershell
uv venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
.\.venv\Scripts\python.exe app.py
```

无需激活虚拟环境。`requirements.txt` 仅包含运行依赖；`requirements-dev.txt` 额外包含打包工具。测试使用 Python 标准库 `unittest`。

## 项目结构

```text
Input-Helper/
├── app.py                    # 界面、热键、文本处理与 Windows 输入发送
├── AutoInputHelper.spec      # PyInstaller 单文件打包配置
├── launch_input_helper.bat   # 使用项目内 .venv 启动
├── requirements.txt         # 运行依赖
├── requirements-dev.txt     # 开发与打包依赖
├── config.example.json      # 可公开提交的示例配置
├── examples/                # 演示输入文本
├── tests/                   # 自动缩进与自动补全回归测试
└── docs/                    # 使用和开发文档
```

`config.json` 在运行时生成，用于保存本地设置和待输入文本，不纳入版本控制。原有 `Q*.txt` 为本地调试资料，公开示例使用 `examples/` 目录。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile app.py tests\test_code_typing.py
```

现有三项回归测试覆盖：

- 减少缩进时，不删除上一行字符，也不将相邻代码行拼接。
- 空行清除自动缩进时，保留上一行内容。
- 自动补全候选可拦截回车时，先关闭候选，保留带尾部换行的注释文本。

测试替换操作系统输入边界，并通过编辑器模型校验最终文本，不向真实窗口发送按键。这些测试无法验证浏览器焦点、编辑器异步响应或所有快捷键配置。涉及输入逻辑的改动，还应在目标编辑器的空白文件中手动核对。

## 构建 Windows 可执行程序

安装开发依赖后执行：

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm AutoInputHelper.spec
```

输出为 `dist/AutoInputHelper.exe`。打包配置使用无控制台、单文件模式；Tcl/Tk 库由 PyInstaller 收集，程序启动时会配置其查找路径。

发布前至少确认程序可以启动、TXT 可以导入，并在目标编辑器中核对短文本、嵌套缩进、空行及自动补全场景。单纯打包成功或进程存活，不等同于输入内容正确。

`build/`、`dist/`、虚拟环境和缓存已通过 `.gitignore` 排除。EXE 可作为单独的发行附件分发，无需加入源码历史；仓库当前不承诺提供预编译下载。

## 当前实现边界

Windows 输入封装使用 `ctypes` 调用 `SendInput`；热键由 `keyboard` 注册；耗时输入在工作线程中运行，界面更新通过 Tkinter 回调调度。

代码模式依赖模拟按键而非编辑器 API。程序不会读取目标窗口文本或验证其状态。停止热键暂停问题和单文件 EXE 配置持久化问题已在 README 中列出，后续修改应分别提供验证证据。
