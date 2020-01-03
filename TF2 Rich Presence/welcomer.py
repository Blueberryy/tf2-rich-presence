# Copyright (C) 2019 Kataiser & https://github.com/Kataiser/tf2-rich-presence/contributors
# https://github.com/Kataiser/tf2-rich-presence/blob/master/LICENSE

import ctypes
import os
import sys

sys.path.append(os.path.abspath(os.path.join('resources', 'python', 'packages')))
sys.path.append(os.path.abspath(os.path.join('resources')))
import colorama

import localization
import settings


def welcome(message_version):
    # localize the window title
    loc = localization.Localizer(language=settings.get('language'))
    ctypes.windll.kernel32.SetConsoleTitleW(loc.text("TF2 Rich Presence ({0})").format('{tf2rpvnum}'))

    print(colorama.Style.BRIGHT, end='')
    print(loc.text("TF2 Rich Presence ({0}) by Kataiser").format('{tf2rpvnum}'))
    print(colorama.Style.RESET_ALL, end='')
    print("https://github.com/Kataiser/tf2-rich-presence\n")
    print(colorama.Style.BRIGHT, end='')

    if message_version == '0':
        print("{}\n".format(loc.text("Launching Team Fortress 2 with Rich Presence enabled...")))
    elif message_version == '1':
        print("{}\n".format(loc.text("Launching TF2 with Rich Presence alongside Team Fortress 2...")))


if __name__ == '__main__':
    welcome(0)
