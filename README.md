# English Vocabulary · 本地单词本

适合个人使用的 Windows 单词本：有道联网查词、自动填入释义与词性、保存词条、每天抽测十词。学习数据保存在本机，不需要 AI 或付费 API 密钥。

## 版本

- `main`：第一版稳定基线，Python + Tkinter + SQLite，含有道自动查词。
- `v2-themes`：第二版，三种可切换主题、卡片与表格词库、排序筛选。

## 第一版运行

需要 Windows 和 Python 3.13。

```powershell
python -m pip install -r src/requirements.txt
python src/main.py
```

默认数据目录为 `D:\CC聊天记录\雅思学习\本地单词本\`。可另设目录：

```powershell
python src/main.py --home 'E:\Vocabulary'
```

打包：在 PowerShell 中执行 `src/build.ps1`，程序输出到 `程序/`。运行打包后的程序无需安装 Python。

## 使用

输入英文或短语，点“有道查词”，浏览自动填好的释义后点“收入单词本”。每天生成固定的十题，新旧词各半；词义回忆和英文拼写混合，答完立即保存，关闭后可继续。支持原格式 Excel 导入、导出、完整备份与恢复。

公开词典网页可能改版或限制访问，查询失败时保留现有内容并提示重试。查词需要网络，已收录词条和抽测可以离线使用。

## 测试

```powershell
cd src
python -m unittest discover -s tests -v
```

33 项测试覆盖查询解析、后台结果隔离、词条管理、每日选词、进度保存、Excel 交换与备份恢复。实时联网验收使用隔离数据：

```powershell
python src/main.py --check-installation --home 'D:\Vocabulary-Check'
```

源码、测试及使用说明可版本管理；个人数据库、原 Excel、备份和本地日志保存在使用者电脑，已加入忽略规则。
