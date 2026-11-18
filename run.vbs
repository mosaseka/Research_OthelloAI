Option Explicit

Dim shell, files, exitCode
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
shell.CurrentDirectory = files.GetParentFolderName(WScript.ScriptFullName)

exitCode = shell.Run("%ComSpec% /d /c run.bat OthelloGUI", 0, True)
If exitCode <> 0 Then
    MsgBox "Othello could not start. Run run.bat from a terminal to see the error.", vbExclamation, "Othello"
End If
WScript.Quit exitCode
