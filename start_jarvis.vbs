Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
py = root & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(py) Then
  sh.Run """" & py & """ """ & root & "\run_jarvis.py""", 0, False
Else
  sh.Run "pythonw """ & root & "\run_jarvis.py""", 0, False
End If
