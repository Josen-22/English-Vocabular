param(
    [switch]$SkipAppBuild,
    [string]$ProgramPath,
    [string]$IsccPath,
    [string]$DependencyDir,
    [string]$OutputDir
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $DependencyDir) { $DependencyDir = Join-Path $repoRoot 'build-tools' }
if (-not $OutputDir) { $OutputDir = Join-Path $repoRoot 'release' }
New-Item -ItemType Directory -Path $DependencyDir,$OutputDir -Force | Out-Null
if (-not $SkipAppBuild) {
    & (Join-Path $repoRoot 'src\build.ps1')
    if ($LASTEXITCODE -ne 0) { throw '程序构建失败。' }
}
if (-not $ProgramPath) { $ProgramPath = Join-Path $repoRoot '程序\本地单词本_进阶版.exe' }
if (-not (Test-Path -LiteralPath $ProgramPath)) { throw '缺少已构建的主程序。' }

function Get-SignedDownload([string]$Url, [string]$Destination, [string]$Publisher) {
    if (-not (Test-Path -LiteralPath $Destination)) {
        Invoke-WebRequest -Uri $Url -OutFile $Destination
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Destination
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch $Publisher) {
        throw "下载文件签名验证失败：$Destination"
    }
}

$webviewBootstrapper = Join-Path $DependencyDir 'MicrosoftEdgeWebview2Setup.exe'
Get-SignedDownload 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' $webviewBootstrapper 'O=Microsoft Corporation'
if (-not $IsccPath) {
    $compilerDir = Join-Path $DependencyDir 'InnoSetup'
    $IsccPath = Join-Path $compilerDir 'ISCC.exe'
    if (-not (Test-Path -LiteralPath $IsccPath)) {
        $innoInstaller = Join-Path $DependencyDir 'innosetup-7.1.1-x64.exe'
        Get-SignedDownload 'https://github.com/jrsoftware/issrc/releases/download/is-7_1_1/innosetup-7.1.1-x64.exe' $innoInstaller 'O=Pyrsys B.V.'
        $compilerInstall = Start-Process -FilePath $innoInstaller -ArgumentList "/CURRENTUSER /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /DIR=`"$compilerDir`"" -WindowStyle Hidden -Wait -PassThru
        if ($compilerInstall.ExitCode -ne 0) { throw '安装 Inno Setup 编译器失败。' }
    }
}
& $IsccPath "/DSourceExe=$ProgramPath" "/DReleaseDir=$OutputDir" "/DDependencyDir=$DependencyDir" (Join-Path $repoRoot 'installer\vocabulary.iss')
if ($LASTEXITCODE -ne 0) { throw '安装包构建失败。' }

$portableDir = Join-Path $OutputDir 'EnglishVocabular-2.1.0-Portable-x64'
New-Item -ItemType Directory -Path $portableDir -Force | Out-Null
Copy-Item -LiteralPath $ProgramPath -Destination (Join-Path $portableDir 'EnglishVocabular.exe')
Copy-Item -LiteralPath (Join-Path $repoRoot 'docs\installation.txt') -Destination (Join-Path $portableDir '使用说明.txt')
Copy-Item -LiteralPath (Join-Path $repoRoot 'docs\learning-guide.md') -Destination (Join-Path $portableDir '进阶版使用说明.md')
$zipPath = Join-Path $OutputDir 'EnglishVocabular-2.1.0-Portable-x64.zip'
Compress-Archive -Path (Join-Path $portableDir '*') -DestinationPath $zipPath -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'docs\installation.txt') -Destination (Join-Path $OutputDir 'README.txt')
$hashLines = @('EnglishVocabular-2.1.0-Setup-x64.exe','EnglishVocabular-2.1.0-Portable-x64.zip','README.txt') | ForEach-Object {
    $itemHash = Get-FileHash -LiteralPath (Join-Path $OutputDir $_) -Algorithm SHA256
    $itemHash.Hash.ToLower() + '  ' + $_
}
$hashLines | Set-Content -LiteralPath (Join-Path $OutputDir 'SHA256SUMS.txt') -Encoding utf8
Write-Output "发布文件已生成：$OutputDir"
