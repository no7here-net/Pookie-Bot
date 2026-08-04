# Pookie Bot - Discord bot for GYATatouille
# Copyright (C) 2026 no7here
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# ========================================================================

# Handles terminal printing and colouring
# E = error
# W = warning
# S = success
# I = info
# O = output (actual error output)

import threading
import datetime
import atexit
import queue
import os

# Log script start time for log file name
_START_TIME = f"{datetime.datetime.now():%Y-%m-%d_-_%H-%M-%S}"

class Logger:
    # Add a threading lock for safe file I/O
    _log_queue = queue.Queue()

    # ANSI Escape Codes for formatting
    _RED = "\033[31m"
    _YELLOW = "\033[33m"
    _GREEN = "\033[32m"
    _BLUE = "\033[34m"
    _PURPLE = "\033[35m"
    _RESET = "\033[0m"
    _BOLD = "\033[1m"

    # ===============
    # LOGGING HELPERS
    # ===============

    # Ensure logs are written in a guaranteed sequence to prevent corruption or race conditions
    @classmethod
    def _worker(cls):
        while True:
            entry = cls._log_queue.get()
            if entry is None:
                break
            try:
                with open(f"logs/{_START_TIME}.log", "a", encoding="utf-8") as f:
                    f.write(entry)
            except Exception as e:
                # Fall back to terminal via the shared emergency printer
                cls._print_fallback("Failed to write to log file.", e)

                # Stop entire bot, even if this is running in a subthread
                os._exit(1)
            finally:
                cls._log_queue.task_done()

    # Shared handler for writing to log file safely
    @classmethod
    def _write_to_log(cls, label: str, message: str, task: bool = False, output: str = None):
        # Fetch current timestamp
        timestamp = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}"

        # Add [ T ] prefix to log if it's a task
        task_msg = "[ T ] " if task else ""

        # Format everything synchronously to guarantee order
        formatted_entry = f"[ {timestamp} ] [ {label} ] {task_msg}{message}\n"

        if output is not None:
            formatted_entry += f"[ {timestamp} ] [ O ] {task_msg}{output}\n"

        # Push to the background worker queue
        cls._log_queue.put(formatted_entry)

    # Shared print and write to log function
    @classmethod
    def _print(cls, label: str, colour: str, message: str, output: str = None, task: bool = False):
        # Fetch current timestamp
        timestamp = f"[{cls._BOLD}{cls._BLUE} {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {cls._RESET}] "

        # Add [ T ] prefix to log if it's a task
        task_msg = f"[{cls._BOLD}{cls._PURPLE} T {cls._RESET}] " if task else ""

        # Add level prefix to log (e.g. [ E ] for error)
        state = f"[{cls._BOLD}{colour} {label} {cls._RESET}] "

        # Print new entry
        print(f"{timestamp}{state}{task_msg}{message}")

        # Write to log file
        cls._write_to_log(label, message, task, output=output)

    # Fallback printer for failures within logging system itself where queue / log file can't be trusted
    @classmethod
    def _print_fallback(cls, message: str, e: Exception):
        # Fetch current timestamp
        timestamp = f"[{cls._BOLD}{cls._BLUE} {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {cls._RESET}] "

        # Add [ E ] prefix to log for error
        state = f"[{cls._BOLD}{cls._RED} E {cls._RESET}] "

        # Print error
        print(f"{timestamp}{state}{message}")
        print(e)

    # ==============
    # PUBLIC METHODS
    # ==============

    @classmethod
    def error(cls, message: str, output: str = None, task: bool = False):
        cls._print("E", cls._RED, message, output=output, task=task)

    @classmethod
    def warning(cls, message: str, output: str = None, task: bool = False):
        cls._print("W", cls._YELLOW, message, output=output, task=task)

    @classmethod
    def success(cls, message: str, output: str = None, task: bool = False):
        cls._print("S", cls._GREEN, message, output=output, task=task)

    @classmethod
    def info(cls, message: str, output: str = None, task: bool = False):
        cls._print("I", cls._BLUE, message, output=output, task=task)

try:
    # Create log folder if it doesn't exist
    if not os.path.exists("logs"):
        os.mkdir("logs")
except Exception as e:
    # Print via the shared emergency printer
    Logger._print_fallback("Failed to start background logging worker thread.", e)

    # Abort
    raise SystemExit(1) from None

try:
    # Start background logging worker thread
    threading.Thread(target=Logger._worker, daemon=True).start()

    # Ensure any remaining logs in the queue are written to the file before the bot completely exits
    @atexit.register
    def _flush_logs():
        Logger.info("Bot shutting down gracefully.")
        Logger._log_queue.join()
except Exception as e:
    # Print via the shared emergency printer
    Logger._print_fallback("Failed to start background logging worker thread.", e)

    # Abort
    raise SystemExit(1) from None

Logger.info(f"Logging started. Writing to \"logs/{_START_TIME}.log\".")
