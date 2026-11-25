#define AppVersion "2.1.0"
#ifndef SourceExe
  #define SourceExe "..\程序\本地单词本_进阶版.exe"
#endif
#ifndef ReleaseDir
  #define ReleaseDir "..\release"
#endif
#ifndef DependencyDir
  #define DependencyDir "..\build-tools"
#endif

[Setup]
AppId={{FE446A4E-BC44-48F1-B4A7-D89B14F803A3}
AppName=本地单词本
AppVersion={#AppVersion}
AppPublisher=Josen-22
AppPublisherURL=https://github.com/Josen-22/English-Vocabular
AppSupportURL=https://github.com/Josen-22/English-Vocabular/issues
DefaultDirName={localappdata}\Programs\EnglishVocabular
DefaultGroupName=本地单词本
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#ReleaseDir}
OutputBaseFilename=EnglishVocabular-{#AppVersion}-Setup-x64
SetupIconFile=..\src\assets\vocab-icon.ico
UninstallDisplayIcon={app}\EnglishVocabular.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
InfoBeforeFile=..\docs\installation.txt
VersionInfoVersion={#AppVersion}
VersionInfoDescription=本地单词本安装程序

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "EnglishVocabular.exe"; Flags: ignoreversion
Source: "..\docs\installation.txt"; DestDir: "{app}"; DestName: "使用说明.txt"; Flags: ignoreversion
Source: "..\docs\learning-guide.md"; DestDir: "{app}"; DestName: "进阶版使用说明.md"; Flags: ignoreversion
Source: "{#DependencyDir}\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{group}\本地单词本"; Filename: "{app}\EnglishVocabular.exe"; AppUserModelID: "Josen22.EnglishVocabular"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"
Name: "{autodesktop}\本地单词本"; Filename: "{app}\EnglishVocabular.exe"; Tasks: desktopicon; AppUserModelID: "Josen22.EnglishVocabular"

[Run]
Filename: "{app}\EnglishVocabular.exe"; Description: "打开本地单词本"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebView2: Boolean;
var
  Version: String;
  ClientKey: String;
begin
  ClientKey := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := ((RegQueryStringValue(HKLM32, ClientKey, 'pv', Version) or
              RegQueryStringValue(HKLM64, ClientKey, 'pv', Version) or
              RegQueryStringValue(HKCU, ClientKey, 'pv', Version)) and
             (Version <> '') and (Version <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  if HasWebView2 then exit;
  WizardForm.StatusLabel.Caption := '正在安装 Microsoft Edge WebView2，请保持联网…';
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install',
              '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Result := '无法启动 WebView2 安装器。请安装 Microsoft Edge WebView2 Runtime 后重试。';
    exit;
  end;
  if not HasWebView2 then
    Result := 'WebView2 尚未安装成功。请联网安装 Microsoft Edge WebView2 Runtime 后重试。安装器退出码：' + IntToStr(ResultCode);
end;
