' ============================================================
'  校园网自动登录 - 启动器
'  优先启动同目录 exe，否则用源码运行（不弹黑窗口）
' ============================================================
Option Explicit

Dim fso, shell, dir, exePath, appPy

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

dir = fso.GetParentFolderName(WScript.ScriptFullName)
exePath = dir & "\校园网自动登录.exe"
appPy = dir & "\app.py"

shell.CurrentDirectory = dir

If fso.FileExists(exePath) Then
    shell.Run """" & exePath & """", 1, False
    WScript.Quit 0
End If

If Not fso.FileExists(appPy) Then
    MsgBox "找不到 校园网自动登录.exe 或 app.py：" & vbCrLf & dir, 16, "校园网自动登录"
    WScript.Quit 1
End If

On Error Resume Next
shell.Run """pythonw.exe"" """ & appPy & """", 1, False
If Err.Number <> 0 Then
    Err.Clear
    shell.Run """python.exe"" """ & appPy & """", 1, False
    If Err.Number <> 0 Then
        MsgBox "未找到 Python，请安装 Python 3 或直接双击 exe。", 16, "校园网自动登录"
        WScript.Quit 1
    End If
End If
On Error GoTo 0