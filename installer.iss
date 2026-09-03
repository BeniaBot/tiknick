; Inno Setup script for Tik-Nick — per-user installer (no admin / no UAC).
; Produces dist\TikNick-Setup.exe which installs TikNick.exe + a marker file
; (install-type.txt) so the app knows to update itself via the installer channel.
;
; Build:  build_installer.bat   (runs build.bat first to produce dist\TikNick.exe)
; Requires: Inno Setup 6 (ISCC.exe).

#define AppName "Tik-Nick"
#define AppVersion "0.8.8"
#define AppExe "TikNick.exe"
#define AppPublisher "בני הבוט"
#define AppURL "https://github.com/BeniaBot/tiknick"

[Setup]
; יציב בין גרסאות — מזהה את ההתקנה לעדכון/הסרה
AppId={{8E7D3C2A-4B1F-4E9A-9C2D-71A0B5E6F8C1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
; התקנה למשתמש הנוכחי בלבד — אין צורך בהרשאות מנהל, ולכן עדכון שקט עובד חלק
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=dist
OutputBaseFilename=TikNick-Setup
SetupIconFile=icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; RTL עברית
ShowLanguageDialog=no
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"

[Tasks]
Name: "desktopicon"; Description: "צור קיצור דרך בשולחן העבודה"; GroupDescription: "קיצורי דרך:"; Flags: checkablealone

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
; קובץ סימון — מסמן לאפליקציה שזו התקנה (עדכון עצמי יעודכן דרך אינסטולר)
Source: "packaging\install-type.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; מפעיל את התוכנה בסיום — גם בהתקנה שקטה (עדכון עצמי), כדי לחזור אוטומטית
Filename: "{app}\{#AppExe}"; Description: "הפעל את {#AppName}"; Flags: nowait postinstall
