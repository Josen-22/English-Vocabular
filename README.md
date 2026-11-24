# English Vocabulary · 本地单词本

适合个人使用的 Windows 单词本：有道联网查词、自动填入释义与词性、保存词条、每天抽测十词。学习数据保存在本机，不需要 AI 或付费 API 密钥。

## 版本

- `main`：第一版稳定基线，Python + Tkinter + SQLite，含有道自动查词。
- `v2-themes`：第二版，三种可切换主题、卡片与表格词库、排序筛选。

## 第二版运行

需要 Windows、Python 3.13 和 Microsoft Edge WebView2 Runtime。第一版仍保留在 `main`。

```powershell
python -m pip install -r src/requirements.txt
python src/desktop.py
```

默认数据目录为 `D:\CC聊天记录\雅思学习\本地单词本\`。可另设目录：

```powershell
python src/desktop.py --home 'E:\Vocabulary'
```

打包：在 PowerShell 中执行 `src/build.ps1`，程序输出到 `程序/本地单词本_第二版.exe`。运行打包后的程序无需安装 Python。

## 三种主题与词库

右上角切换“清爽学习 / 纸感手册 / 深色专注”。主题有各自的颜色、字体和导航布局，切换保留正在编辑的内容和抽测进度，并记住选择。

词库提供卡片、表格两种视图，以及 9 种排序：最近/最早加入、字母正序/倒序、掌握度升序/降序、复习日期、正确率、最久未复习。支持全部、新词、到期词、薄弱词、学习中和已掌握筛选。排序和筛选可组合搜索，未测试词条在正确率排序中放在末尾。

详情包含完整释义、来源、备注和复习历史。数据库格式兼容第一版，两版共用现有学习数据。

详见 [第二版使用说明](docs/v2-guide.md)、[设计约定](docs/v2-design.md) 和 [后续改进建议](docs/next-steps.md)。

## 使用

输入英文或短语，点“有道查词”，浏览自动填好的释义后点“收入单词本”。每天生成固定的十题，新旧词各半；词义回忆和英文拼写混合，答完立即保存，关闭后可继续。支持原格式 Excel 导入、导出、完整备份与恢复。

公开词典网页可能改版或限制访问，查询失败时保留现有内容并提示重试。查词需要网络，已收录词条和抽测可以离线使用。

## 测试

```powershell
cd src
python -m unittest discover -s tests -v
```

39 项测试覆盖查询解析、后台结果隔离、词条管理、每日选词、进度保存、Excel 交换、备份恢复，以及词库筛选排序、主题设置持久化和桌面调用线程安全。实际 WebView2 联网验收使用隔离数据：

```powershell
python src/desktop.py --check-installation --home 'D:\Vocabulary-Check'
```

浏览器交互回归（需要本机 Edge）：

```powershell
npm install
npm run test:ui
```

覆盖三主题、草稿保留、查词收录、卡片/表格、搜索筛选、详情、抽测和 760/1024/1440 宽度检查，测试数据和报告仅写入忽略的 `验证/` 目录。

界面全部在本地打包，不依赖外部 CDN、字体、账号或云服务。源码、测试及使用说明可版本管理；个人数据库、原 Excel、备份和本地日志保存在使用者电脑，已加入忽略规则。
