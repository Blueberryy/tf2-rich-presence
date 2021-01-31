# cython: language_level=3

"""Discord Rich Presence for Team Fortress 2"""

# TF2 Rich Presence
# https://github.com/Kataiser/tf2-rich-presence
#
# Copyright (C) 2018-2021 Kataiser & https://github.com/Kataiser/tf2-rich-presence/contributors
# https://github.com/Kataiser/tf2-rich-presence/blob/master/LICENSE
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import datetime
import gc
import os
import platform
import time
import traceback
from typing import Any, Dict, Optional, Set, Tuple, Union

import psutil
from discoIPC import ipc

import configs
import console_log
import game_state
import gui
import launcher
import localization
import logger
import processes
import settings
import utils

__author__ = "Kataiser"
__copyright__ = "Copyright (C) 2018-2021 Kataiser & https://github.com/Kataiser/tf2-rich-presence/contributors"
__license__ = "GPL-3.0"
__email__ = "Mecharon1.gm@gmail.com"


def launch():
    try:
        gc.disable()

        log_main: logger.Log = logger.Log()
        log_main.to_stderr = launcher.DEBUG
        log_main.info(f"Starting TF2 Rich Presence {launcher.VERSION}")

        app: TF2RichPresense = TF2RichPresense(log_main)
        app.run()
    except SystemExit:
        raise
    except Exception:
        try:
            gc.enable()
            log_main.critical(traceback.format_exc())
        except NameError:
            pass  # the crash happened in logger.Log().__init__() and so log_main is unassigned

        raise


class TF2RichPresense:
    def __init__(self, log: Optional[logger.Log] = None, set_process_priority: bool = True):
        if log:
            self.log: logger.Log = log
        else:
            self.log = logger.Log()
            self.log.error(f"Initialized main.TF2RichPresense without a log, defaulting to one at {self.log.filename}")

        settings.fix_settings(self.log)
        default_settings: dict = settings.defaults()
        current_settings: dict = settings.access_registry()

        if current_settings == default_settings:
            self.log.debug("Current settings are default")
        else:
            self.log.debug(f"Non-default settings: {settings.compare_settings(default_settings, current_settings)}")

        self.gui: gui.GUI = gui.GUI(self.log)
        self.process_scanner: processes.ProcessScanner = processes.ProcessScanner(self.log)
        self.loc: localization.Localizer = localization.Localizer(self.log)
        self.game_state = game_state.GameState(self.log, self.loc)
        self.rpc_client: Optional[ipc.DiscordIPC] = None
        self.client_connected: bool = False
        self.rpc_connected: bool = False
        self.test_state: str = 'init'
        self.activity: dict = {}
        self.should_mention_discord: bool = True
        self.should_mention_tf2: bool = True
        self.should_mention_steam: bool = True
        self.has_checked_class_configs: bool = False
        self.has_seen_kataiser: bool = False
        self.console_log_mtime: Optional[int] = None
        self.old_console_log_mtime: Optional[int] = None
        self.loop_iteration: int = 0
        self.custom_functions = None
        self.valid_usernames: Set[str] = set()
        self.last_name_scan_time: float = time.time()  # close enough
        self.steam_config_mtimes: Dict[str, int] = {}
        self.cleanup_primed: bool = True
        self.slow_sleep_time: bool = False
        self.has_set_process_priority: bool = not set_process_priority
        self.kataiser_scan_loop: int = 0
        self.did_init_operations: bool = False
        self.no_condebug: bool = False
        self.fast_next_loop: bool = False

        try:
            self.log.cleanup(20 if launcher.DEBUG else 10)
        except (FileNotFoundError, PermissionError):
            self.log.error(f"Couldn't clean up logs folder:\n{traceback.format_exc()}")

        self.log.debug(f"CPU: {psutil.cpu_count(logical=False)} cores, {psutil.cpu_count()} threads, {round(psutil.cpu_freq().max / 1000, 1)} GHz")

        platform_info: Dict[str, Any] = {'architecture': platform.architecture, 'machine': platform.machine, 'system': platform.system, 'platform': platform.platform,
                                         'processor': platform.processor, 'python_version_tuple': platform.python_version_tuple}
        for platform_part in platform_info:
            try:
                if platform_part == 'platform':
                    platform_info[platform_part] = platform_info[platform_part](aliased=True)
                else:
                    platform_info[platform_part] = platform_info[platform_part]()
            except Exception:
                self.log.error(f"Exception during platform.{platform_part}(), skipping\n{traceback.format_exc()}")
        self.log.debug(f"Platform: {platform_info}")

        if not os.path.supports_unicode_filenames:
            self.log.error("Looks like the OS doesn't support unicode filenames. This might cause problems")

        self.import_custom()

    def __repr__(self) -> str:
        return f"main.TF2RichPresense (state={self.test_state})"

    # import custom functionality
    def import_custom(self):
        custom_functions_path: str = os.path.join('resources', 'custom.py') if os.path.isdir('resources') else 'custom.py'

        if os.path.isfile(custom_functions_path):
            with open(custom_functions_path, 'r') as custom_functions_file:
                custom_functions_lines: int = len(custom_functions_file.readlines())

            import custom
            self.log.debug(f"Imported custom.py ({custom_functions_lines} lines)")
            self.custom_functions = custom.TF2RPCustom()  # good naming
        else:
            self.log.debug("custom.py doesn't exist")

    def run(self):
        while True:
            self.loop_body()

            # rich presence only updates every 15 seconds, but it listens constantly so sending every 2 or 5 seconds (by default) is probably fine
            sleep_time: int = settings.get('wait_time_slow') if self.slow_sleep_time else settings.get('wait_time')
            sleep_time_started: float = time.perf_counter()
            self.log.debug(f"Sleeping for {sleep_time} seconds (slow = {self.slow_sleep_time})")

            while time.perf_counter() - sleep_time_started < sleep_time and self.gui.alive and not self.fast_next_loop:
                time.sleep(1 / 30)  # 30 Hz updates (btw tell me if this is stupid)
                self.gui.safe_update()

    # the main logic. runs every 2 or 5 seconds (by default)
    def loop_body(self):
        # because closing the GUI doesn't actually exit the program
        if not self.gui.alive:
            del self.log
            raise SystemExit

        self.slow_sleep_time = False
        self.loop_iteration += 1
        self.log.debug(f"Main loop iteration this app session: {self.loop_iteration}")
        self.no_condebug = False  # this will be updated by either console_log.py or configs.py if need be
        self.fast_next_loop = False

        if self.custom_functions:
            self.custom_functions.before_loop(self)

        p_data: Dict[str, Dict[str, Union[bool, str, int, None]]] = self.process_scanner.scan()

        # reads steam config files to find usernames with -condebug (on first loop, and if any of them have been modified)
        if p_data['Steam']['running']:
            config_scan_needed: bool = self.steam_config_mtimes == {}

            for steam_config in self.steam_config_mtimes:
                old_mtime: int = self.steam_config_mtimes[steam_config]
                new_mtime: int = int(os.stat(steam_config).st_mtime)

                if new_mtime > old_mtime:
                    self.log.debug(f"Rescanning Steam config files ({new_mtime} > {old_mtime} for {steam_config})")
                    config_scan_needed = True

            if config_scan_needed:
                steam_config_results: Optional[Set[str]] = self.steam_config_file(p_data['Steam']['path'])

                if steam_config_results:
                    self.valid_usernames.update(steam_config_results)
                    self.log.debug(f"Usernames with -condebug: {self.valid_usernames}")
                else:
                    self.no_condebug = True
        elif p_data['Steam']['pid'] is not None or p_data['Steam']['path'] is not None:
            self.log.error(f"Steam isn't running but its process info is {p_data['Steam']}. WTF?")

        if p_data['TF2']['running'] and p_data['Discord']['running'] and p_data['Steam']['running']:
            if not p_data['Steam']['running'] and p_data['TF2']['running']:
                self.log.error("TF2 is running but Steam isn't. WTF?")

            if not self.has_checked_class_configs:
                # modifies a few tf2 config files
                configs.class_config_files(self.log, p_data['TF2']['path'])
                self.has_checked_class_configs = True

            self.game_state.game_start_time = p_data['TF2']['time']
            self.gui.set_clean_console_log_button_state(True)

            console_log_path: str = os.path.join(p_data['TF2']['path'], 'tf', 'console.log')
            console_log_parsed: Optional[Tuple[bool, str, str, str, str, bool]] = self.interpret_console_log(console_log_path, self.valid_usernames, tf2_start_time=p_data['TF2']['time'])
            self.old_console_log_mtime = self.console_log_mtime

            if console_log_parsed:
                self.game_state.set_bulk(console_log_parsed)

            time_elapsed_num: str = str(datetime.timedelta(seconds=int(time.time() - p_data['TF2']['time'])))
            time_elapsed: str = self.loc.text("{0} elapsed").format(time_elapsed_num.removeprefix('0:').removeprefix('0'))
            base_window_title: str = self.loc.text("TF2 Rich Presence ({0})").format(launcher.VERSION)
            window_title_format_menus: str = self.loc.text("{0} - {1} ({2})")
            window_title_format_main: str = self.loc.text("{0} - {1} on {2}")

            # most of this is GUI handling
            # TODO: move setting GUI from game_state into a separate function
            if self.game_state.in_menus:
                # in menus mean the main menu
                self.test_state = 'menus'
                window_title: str = window_title_format_menus.format(base_window_title, "In menus", self.loc.text(self.game_state.queued_state))

                self.gui.set_state_3('main_menu', ("In menus", self.game_state.queued_state, time_elapsed))
                self.gui.clear_fg_image()
                self.gui.clear_class_image()

                if self.game_state.queued_state == "Queued for Casual":
                    self.gui.set_fg_image('casual')
                elif self.game_state.queued_state == "Queued for Competitive":
                    self.gui.set_fg_image('comp')
                elif "Queued for MvM" in self.game_state.queued_state:
                    self.gui.set_fg_image('mvm_queued')
                else:
                    self.gui.set_fg_image('tf2_logo')
            else:  # not in menus = in a match
                self.test_state = 'in game'
                window_title = window_title_format_main.format(base_window_title, self.game_state.tf2_class, self.game_state.map_fancy)

                # get server data, if needed (game_state doesn't handle it itself)
                server_modes = []
                if settings.get('top_line') in ('Player count', 'Kills'):
                    server_modes.append(settings.get('top_line'))
                if settings.get('bottom_line') in ('Player count', 'Kills'):
                    server_modes.append(settings.get('bottom_line'))
                self.game_state.set_server_data(server_modes, self.valid_usernames)

                if self.game_state.gamemode == "Unknown gamemode":
                    bg_image: str = 'bg_modes/unknown'
                else:
                    bg_image = f'bg_modes/{self.game_state.gamemode}'

                self.gui.set_state_4(bg_image, (self.game_state.map_line, self.game_state.get_line('top'), self.game_state.get_line('bottom'), time_elapsed))
                self.gui.set_class_image(self.game_state.tf2_class)

                if self.game_state.custom_map or self.game_state.tf2_map in game_state.excluded_maps:
                    if self.game_state.gamemode == 'unknown':
                        self.gui.set_fg_image('fg_modes/unknown')
                    else:
                        self.gui.set_fg_image(f'fg_modes/{self.game_state.gamemode}')
                else:
                    if self.game_state.tf2_map in game_state.map_fallbacks:
                        self.gui.set_fg_image(f'fg_maps/{game_state.map_fallbacks[self.game_state.tf2_map]}')
                    else:
                        self.gui.set_fg_image(f'fg_maps/{self.game_state.tf2_map}')

            if self.game_state.update_rpc:
                self.activity = self.game_state.activity()

                # let this make some last-second adjustments to activity
                if self.custom_functions:
                    self.custom_functions.loop_middle(self)

                self.send_rpc_activity()
            else:
                self.log.debug("Not updating RPC state")

                # not a lot of useful stuff this can do here, but it should still get the chance to run
                if self.custom_functions:
                    self.custom_functions.loop_middle(self)

            self.gui.master.title(window_title)
            self.log.debug(f"Set window title to \"{window_title}\"")

        elif not p_data['TF2']['running']:
            self.necessary_program_not_running('Team Fortress 2', 'TF2')
            self.should_mention_tf2 = False
        elif not p_data['Discord']['running']:
            self.necessary_program_not_running('Discord')
            self.should_mention_discord = False
        else:
            # last but not least, Steam
            self.necessary_program_not_running('Steam')
            self.should_mention_steam = False

        if self.custom_functions:
            self.custom_functions.after_loop(self)

        self.gui.safe_update()
        self.init_operations()

        if self.no_condebug:
            self.gui.no_condebug_warning()
            self.fast_next_loop = True

        if not self.has_set_process_priority:
            self_process: psutil.Process = psutil.Process()
            priorities_before: tuple = (self_process.nice(), self_process.ionice())
            self_process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            self_process.ionice(psutil.IOPRIO_LOW)
            priorities_after: tuple = (self_process.nice(), self_process.ionice())
            self.log.debug(f"Set process priorities from {priorities_before} to {priorities_after}")
            self.has_set_process_priority = True

        if not gc.isenabled():
            gc.enable()
            gc.collect()
            self.log.debug("Enabled GC and collected")

        return self.client_connected, self.rpc_client

    def necessary_program_not_running(self, program_name: str, name_short: str = ''):
        name_short = program_name if not name_short else name_short
        self.test_state = f'no {name_short.lower()}'
        self.slow_sleep_time = True  # update less often if not all programs are running

        if self.client_connected:
            self.log.debug("Disconnecting RPC client")
            self.rpc_client.disconnect()
            self.client_connected = False

        self.gui.set_state_1('default', "Team Fortress 2 isn't running")
        self.gui.clear_fg_image()
        self.gui.clear_class_image()
        self.gui.set_clean_console_log_button_state(False)
        self.gui.clean_console_log = False

        base_window_title: str = self.loc.text("TF2 Rich Presence ({0})").format(launcher.VERSION)
        window_title: str = self.loc.text("{0} - Waiting for {1}").format(base_window_title, program_name)
        self.gui.master.title(window_title)
        self.log.debug(f"Set window title to \"{window_title}\"")

    # sends RPC data, connecting to Discord initially if need be
    def send_rpc_activity(self):
        try:
            if not self.client_connected:
                # connects to Discord
                self.rpc_client = ipc.DiscordIPC(utils.get_api_key('discord2'))
                self.rpc_client.connect()

            self.rpc_client.update_activity(self.activity)
            self.log.info(f"Sent over RPC: {self.activity}")
            client_state: tuple = (self.rpc_client.client_id, self.rpc_client.connected, self.rpc_client.ipc_path, self.rpc_client.pid, self.rpc_client.platform, self.rpc_client.socket)
            self.log.debug(f"Client state: {client_state}")
            self.client_connected = True
        except Exception as client_connect_error:
            if str(client_connect_error) in ("Can't send data to Discord via IPC.", "Can't connect to Discord Client."):
                # often happens when Discord is in the middle of starting up
                # TODO: maybe show this in the GUI
                self.log.error(str(client_connect_error), reportable=False)
            else:
                raise

    # do stuff that was previously in init.py, but only after one main loop so that the GUI is ready
    def init_operations(self):
        if not self.did_init_operations:
            self.did_init_operations = True
            self.gui.safe_update()
            self.log.debug("Performing init operations")
            localization.detect_system_language(self.log)
            self.gui.holiday()

            if settings.get('check_updates'):
                self.gui.check_for_updates(False)
            else:
                self.log.debug("Updater is disabled, skipping")

    # reads a console.log and returns current map and class
    def interpret_console_log(self, *args, **kwargs) -> Optional[Tuple[bool, str, str, str, str, bool]]:
        return console_log.interpret(self, *args, **kwargs)

    # reads steam's launch options save file to find usernames with -condebug
    def steam_config_file(self, *args, **kwargs) -> Optional[Set[str]]:
        return configs.steam_config_file(self, *args, **kwargs)


if __name__ == '__main__':
    launch()
