:: Copyright (C) 2019 Kataiser & https://github.com/Kataiser/tf2-rich-presence/contributors
:: https://github.com/Kataiser/tf2-rich-presence/blob/master/LICENSE

:: These batch launchers are for debugging and function identically to their corresponding EXEs (unless modified).

@echo off

if not exist resources\ ( 
    cd ..
    if not exist resources\ ( 
        echo Resources folder missing, exiting
        goto bail
    )
)

start "" "resources\python-3.7.9-embed-win32\pythonw.exe" -I "resources\launcher.py" --m settings
goto close

:bail
pause

:close