Set WshShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetFile(WScript.ScriptFullName).ParentFolder.Path

' ─── Evitar ejecución múltiple ──────────────────────────────────────────
Dim lockFile
lockFile = scriptDir & "\start_backend.lock"
Set fso = CreateObject("Scripting.FileSystemObject")

' Si el lock tiene menos de 30 segundos, otro VBS ya está corriendo
If fso.FileExists(lockFile) Then
    Set lockFileObj = fso.GetFile(lockFile)
    Dim ageSeconds
    ageSeconds = DateDiff("s", lockFileObj.DateLastModified, Now)
    If ageSeconds < 30 Then
        WScript.Quit  ' Ya hay una instancia ejecutándose
    End If
End If

' Crear lock
Set lockFileObj = Nothing
fso.CreateTextFile(lockFile, True).Close

Sub KillOurProcesses(strExe)
    On Error Resume Next
    Set objWMIService = GetObject("winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2")
    Set colProcess = objWMIService.ExecQuery("Select * from Win32_Process Where Name = '" & strExe & "'")
    For Each objProcess In colProcess
        If InStr(objProcess.CommandLine, scriptDir) > 0 Then
            On Error Resume Next
            objProcess.Terminate()
            On Error Resume Next
        End If
    Next
End Sub

' Matar TODOS los procesos python de nuestra carpeta (2 pases forzados)
KillOurProcesses "pythonw.exe"
KillOurProcesses "python.exe"
WScript.Sleep 2000
KillOurProcesses "pythonw.exe"
KillOurProcesses "python.exe"
WScript.Sleep 2000

' Iniciar el Watchdog CON PRIVILEGIOS DE ADMIN (él se encargará de iniciar el resto)
' BlockInput requiere admin para bloquear mouse/teclado durante el writeback.
' Ruta ABSOLUTA obligatoria: con ruta relativa la línea de comandos del
' watchdog no contiene scriptDir y KillOurProcesses nunca lo encuentra,
' dejando watchdogs viejos vivos tras cada reinicio.
WshShell.CurrentDirectory = scriptDir
CreateObject("Shell.Application").ShellExecute "pythonw", """" & scriptDir & "\backend_watchdog.py""", scriptDir, "runas", 0


' Limpiar lock
On Error Resume Next
fso.DeleteFile lockFile, True
On Error Resume Next

Set WshShell = Nothing
