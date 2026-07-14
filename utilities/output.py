# Handles terminal printing and colouring
# E = error
# W = warning
# S = success
# I = info
# O = output (actual error output)

import threading
import datetime
import asyncio
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
                # Fall back to terminal

                # Fetch current timestamp
                timestamp = f"[{Logger._BOLD}{Logger._BLUE} {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {Logger._RESET}] "

                # Add [ E ] prefix to log for error
                state = f"[{Logger._BOLD}{Logger._RED} E {Logger._RESET}] "

                print(f"{timestamp}{state}Failed to write to log file.")
                print(e)

                # Stop entire bot, even if this is running in a subthread
                os._exit(1)
            finally:
                cls._log_queue.task_done()

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

    @classmethod
    def error(cls, message: str, output: str = None, task: bool = False):
        # Fetch current timestamp
        timestamp = f"[{Logger._BOLD}{Logger._BLUE} {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {Logger._RESET}] "

        # Add [ T ] prefix to log if it's a task
        task_msg = f"[{Logger._BOLD}{Logger._PURPLE} T {Logger._RESET}] " if task else ""

        # Add [ E ] prefix to log for error
        state = f"[{Logger._BOLD}{Logger._RED} E {Logger._RESET}] "

        # Print new entry
        print(f"{timestamp}{state}{task_msg}{message}")

        # Write to log file
        cls._write_to_log("E", message, task, output=output)

    @classmethod
    def warning(cls, message: str, output: str = None, task: bool = False):
        # Fetch current timestamp
        timestamp = f"[{Logger._BOLD}{Logger._BLUE} {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {Logger._RESET}] "

        # Add [ T ] prefix to log if it's a task
        task_msg = f"[{Logger._BOLD}{Logger._PURPLE} T {Logger._RESET}] " if task else ""

        # Add [ W ] prefix to log for warning
        state = f"[{Logger._BOLD}{Logger._YELLOW} W {Logger._RESET}] "

        # Print new entry
        print(f"{timestamp}{state}{task_msg}{message}")

        # Write to log file
        cls._write_to_log("W", message, task, output=output)

    @classmethod
    def success(cls, message: str, output: str = None, task: bool = False):
        # Fetch current timestamp
        timestamp = f"[{Logger._BOLD}{Logger._BLUE} {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {Logger._RESET}] "

        # Add [ T ] prefix to log if it's a task
        task_msg = f"[{Logger._BOLD}{Logger._PURPLE} T {Logger._RESET}] " if task else ""

        # Add [ S ] prefix to log for success
        state = f"[{Logger._BOLD}{Logger._GREEN} S {Logger._RESET}] "

        # Print new entry
        print(f"{timestamp}{state}{task_msg}{message}")

        # Write to log file
        cls._write_to_log("S", message, task, output=output)

    @classmethod
    def info(cls, message: str, output: str = None, task: bool = False):
        # Fetch current timestamp
        timestamp = f"[{Logger._BOLD}{Logger._BLUE} {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {Logger._RESET}] "

        # Add [ T ] prefix to log if it's a task
        task_msg = f"[{Logger._BOLD}{Logger._PURPLE} T {Logger._RESET}] " if task else ""

        # Add [ I ] prefix to log for info
        state = f"[{Logger._BOLD}{Logger._BLUE} I {Logger._RESET}] "

        # Print new entry
        print(f"{timestamp}{state}{task_msg}{message}")

        # Write to log file
        cls._write_to_log("I", message, task, output=output)

try:
    # Create log folder if it doesn't exist
    if not os.path.exists("logs"):
        os.mkdir("logs")
except Exception as e:
    # Fetch current timestamp
    timestamp = f"[{Logger._BOLD}{Logger._BLUE} {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {Logger._RESET}] "

    # Add [ E ] prefix to log for error
    state = f"[{Logger._BOLD}{Logger._RED} E {Logger._RESET}] "

    # Print error
    print(f"{timestamp}{state}Failed to create logs folder.")
    print(e)

    # Abort
    raise SystemExit(1)

try:
    # Start background logging worker thread
    threading.Thread(target=Logger._worker, daemon=True).start()

    # Ensure any remaining logs in the queue are written to the file before the bot completely exits
    @atexit.register
    def _flush_logs():
        Logger.info("Bot shutting down gracefully.")
        Logger._log_queue.join()
except Exception as e:
    # Fetch current timestamp
    timestamp = f"[{Logger._BOLD}{Logger._BLUE} {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {Logger._RESET}] "

    # Add [ E ] prefix to log for error
    state = f"[{Logger._BOLD}{Logger._RED} E {Logger._RESET}] "

    # Print error
    print(f"{timestamp}{state}Failed to start background logging worker thread.")
    print(e)

    # Abort
    raise SystemExit(1)

Logger.info(f"Logging started. Writing to \"logs/{_START_TIME}.log\".")
