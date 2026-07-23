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

' Iniciar el Watchdog NO ELEVADO (él se encargará de iniciar el resto).
' ⚠ NO usar "runas"/elevación aquí (revertido 2026-07-23 tras romper H: en prod):
' H: es una unidad de RED MAPEADA del usuario (\\192.168.1.118\Happs) y un proceso
' ELEVADO NO ve las unidades mapeadas (salvo EnableLinkedConnections=1 en el
' registro, que NO está seteado) -> el backend elevado deja de ver H: y TODO
' (extracción, sync, writeback, widget) reporta "H: desconectada" aunque el
' Explorador la vea. La elevación se había agregado (commit 358c06e) para el
' BlockInput del writeback, pero ese bloqueo es OPCIONAL (el banner topmost + F12
' protegen igual) y NO justifica perder el acceso a H:.
' Ruta ABSOLUTA obligatoria: con ruta relativa la línea de comandos del watchdog
' no contiene scriptDir y KillOurProcesses nunca lo encuentra, dejando watchdogs
' viejos vivos tras cada reinicio.
WshShell.CurrentDirectory = scriptDir
WshShell.Run "pythonw """ & scriptDir & "\backend_watchdog.py""", 0, False


' Limpiar lock
On Error Resume Next
fso.DeleteFile lockFile, True
On Error Resume Next

Set WshShell = Nothing
