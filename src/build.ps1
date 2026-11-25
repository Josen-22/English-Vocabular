param([string]$BuildPython)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
if (-not $BuildPython) { $BuildPython = Join-Path $PSScriptRoot '..\构建环境\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $buildPython)) {
    python -m venv ..\构建环境
    if ($LASTEXITCODE -ne 0) { throw '创建独立构建环境失败。' }
}
& $buildPython -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw '安装构建依赖失败。' }
& $buildPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw '测试未通过，停止打包。' }
$webAssets = (Join-Path $PSScriptRoot 'web') + ';web'
$iconAssets = (Join-Path $PSScriptRoot 'assets') + ';assets'
$appIcon = Join-Path $PSScriptRoot 'assets\vocab-icon.ico'
$appVersion = Join-Path $PSScriptRoot 'version_info.txt'
& $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name 本地单词本_进阶版 --icon $appIcon --version-file $appVersion --distpath ..\程序 --workpath ..\构建缓存 --specpath ..\构建缓存 --add-data $webAssets --add-data $iconAssets --exclude-module numpy --exclude-module pandas --exclude-module matplotlib --exclude-module scipy --exclude-module PIL --exclude-module IPython --exclude-module pytest --exclude-module PySide6 --exclude-module PyQt5 --exclude-module gi --exclude-module cefpython3 desktop.py
if ($LASTEXITCODE -ne 0) { throw '打包失败。' }
Write-Output '已生成：程序\本地单词本_进阶版.exe'
