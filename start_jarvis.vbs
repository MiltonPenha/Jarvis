Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\PC Gamer\Desktop\jarvis"
WshShell.Run """C:\Python314\python.exe"" ""C:\Users\PC Gamer\Desktop\jarvis\run_jarvis.py""", 0, False
