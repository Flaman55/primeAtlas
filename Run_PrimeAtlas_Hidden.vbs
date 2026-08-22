' Run_PrimeAtlas_Hidden.vbs -- launches Run_PrimeAtlas.bat in a hidden window
' (style 0), so that during normal use (e.g. a Desktop shortcut) there's no black
' console visible alongside the app window for the whole time the app is running.
'
' Double-clicking the .bat launches it in a cmd.exe window, which sits there line by
' line waiting for the "python prime_atlas_v1.py" command to finish (see
' Run_PrimeAtlas.bat) -- that's the cmd.exe console itself, not something created by
' Python, and it stays visible for the app's entire runtime.
'
' This .vbs works around that: it launches the SAME .bat (with no changes to it) via
' WScript.Shell.Run with an explicitly hidden window style (0), so no console ever
' shows up. Run_PrimeAtlas.bat is left untouched and still works normally as plan B --
' run it DIRECTLY (not through this .vbs) when you need to see the full startup error
' text (e.g. Python not found in PATH) in the console instead of in the message box
' below.
'
' The Desktop / Start Menu shortcut should point at THIS file (.vbs), not at the .bat.
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = fso.BuildPath(scriptDir, "Run_PrimeAtlas.bat")

If Not fso.FileExists(batPath) Then
    MsgBox "File not found:" & vbCrLf & batPath, vbCritical, "PrimeAtlas"
    WScript.Quit 1
End If

cmd = """" & batPath & """"
' 0 = hidden window, True = wait for completion and return the exit code (needed to
' even know whether startup failed at all -- with False, Run() would return 0 immediately).
exitCode = WshShell.Run(cmd, 0, True)

If exitCode <> 0 Then
    MsgBox "PrimeAtlas exited with an error (code " & exitCode & ")." & vbCrLf & vbCrLf & _
           "Run Run_PrimeAtlas.bat directly (double-click) to see the error " & _
           "details in the console.", _
           vbExclamation, "PrimeAtlas"
End If
