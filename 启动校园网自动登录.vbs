' ============================================================
'  Campus network auto-login - GUI launcher
'  Double-click this file to open the app (no console window).
' ============================================================
Option Explicit

Dim fso, shell, scriptDir, guiFile, pywCmd

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
guiFile = scriptDir & "\gui.py"

If Not fso.FileExists(guiFile) Then
    MsgBox "Cannot find gui.py in:" & vbCrLf & scriptDir, 16, "Campus Auto Login"
    WScript.Quit 1
End If

shell.CurrentDirectory = scriptDir

On Error Resume Next
pywCmd = """pythonw.exe"" """ & guiFile & """"
shell.Run pywCmd, 1, False
If Err.Number <> 0 Then
    Err.Clear
    ' pythonw not in PATH, try python
    shell.Run """python.exe"" """ & guiFile & """", 1, False
    If Err.Number <> 0 Then
        MsgBox "Python not found." & vbCrLf & vbCrLf & _
               "Please install Python 3 and make sure it is in PATH.", 16, "Campus Auto Login"
        WScript.Quit 1
    End If
End If
On Error GoTo 0
