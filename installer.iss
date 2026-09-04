; Inno Setup script for Tik-Nick — per-user installer (no admin / no UAC).
; Produces dist\TikNick-Setup.exe which installs TikNick.exe + a marker file
; (install-type.txt) so the app knows to update itself via the installer channel.
;
; Build:  build_installer.bat   (runs build.bat first to produce dist\TikNick.exe)
; Requires: Inno Setup 6 (ISCC.exe).

#define AppName "Tik-Nick"
#define AppVersion "0.8.15"
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
; אין כאן AppMutex במכוון. הוא נוסה ב-0.8.13 ועשה נזק: לקוח ישן מריץ את ה-Setup
; במקביל לתוכנה שעדיין חיה, המנעול תפוס, ובהתקנה שקטה ההודעה מדוכאת ו-Inno עונה
; עליה Cancel בעצמו ("Got EAbort exception") — כלומר אף גרסה ישנה לא הצליחה
; לעדכן. במקום זה: ClosePrograms ב-[Code] סוגר בפועל את מה שחוסם.
; רקע: מחיקת קובץ הרצה מחזירה Access denied (5) ולא "בשימוש" (32), כי הדמות
; ממופה לזיכרון — ולכן גם השגיאה לא רמזה למשתמש מה לעשות.
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"

[Messages]
; ברירת המחדל של Inno כאן גנרית; זו ההודעה שהמשתמש באמת רואה כשהתוכנה פתוחה.
hebrew.SetupAppRunningError=Tik-Nick פתוחה כרגע.%n%nסגור אותה לגמרי (כולל חלון שרץ ברקע) ואז לחץ "אישור" כדי להמשיך, או "ביטול" כדי לצאת.

[Tasks]
Name: "desktopicon"; Description: "צור קיצור דרך בשולחן העבודה"; GroupDescription: "קיצורי דרך:"; Flags: checkablealone

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
; קובץ סימון — מסמן לאפליקציה שזו התקנה (עדכון עצמי יעודכן דרך אינסטולר)
Source: "packaging\install-type.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Code]
// PyInstaller onefile מריץ שני תהליכים: אב (בלי חלון) שמחלץ ל-_MEI, ובן עם
// החלון. כשהמשתמש סוגר את החלון הבן מת — והאב נשאר, בלי חלון, ומחזיק את דמות
// ה-EXE. Restart Manager לא מצליח לסגור אותו ("Some applications could not be
// shut down"), ולכן ההתקנה הגיעה עד DeleteFile ונפלה.
// כאן סוגרים אותו בפועל, ממש לפני העתקת הקבצים. אין מה לאבד: לתהליך הזה אין
// חלון ואין מצב לא שמור — המאגר נכתב ב-SQLite עם WAL בכל פעולה.
function CloseRunningApp(): Boolean;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/c powershell -NoProfile -ExecutionPolicy Bypass -Command "' +
       '$ErrorActionPreference=''SilentlyContinue'';' +
       'Get-Process -Name TikNick | Stop-Process -Force;' +
       'Start-Sleep -Milliseconds 900;' +
       'exit 0"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunningApp();
  Result := '';
end;

[Run]
; מפעיל את התוכנה בסיום — גם בהתקנה שקטה (עדכון עצמי), כדי לחזור אוטומטית
Filename: "{app}\{#AppExe}"; Description: "הפעל את {#AppName}"; Flags: nowait postinstall
