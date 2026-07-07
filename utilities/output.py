# Handles terminal printing and colouring
# E = error
# W = warning
# S = success
# I = info
# O = output (actual error output)

import datetime

# Log script start time for log file name
_START_TIME = datetime.datetime.now().strftime("%Y-%m-%d_-_%H-%M-%S")

class Logger:
    # ANSI Escape Codes for formatting
    _RED = "\033[31m"
    _YELLOW = "\033[33m"
    _GREEN = "\033[32m"
    _BLUE = "\033[34m"
    _RESET = "\033[0m"
    _BOLD = "\033[1m"

    @classmethod
    def _write_to_log(cls, label: str, message: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(f"logs/{_START_TIME}.log", "a", encoding="utf-8") as f:
            f.write(f"[ {timestamp} ] [ {label} ] {message}\n")

    @classmethod
    def error(cls, message: str, output: str = None):
        print(f"[{Logger._BOLD}{Logger._RED} E {Logger._RESET}] {message}")
        cls._write_to_log("E", message)

        if output != None:
            cls._write_to_log("O", output)

    @classmethod
    def warning(cls, message: str):
        print(f"[{Logger._BOLD}{Logger._YELLOW} W {Logger._RESET}] {message}")
        cls._write_to_log("W", message)

    @classmethod
    def success(cls, message: str):
        print(f"[{Logger._BOLD}{Logger._GREEN} S {Logger._RESET}] {message}")
        cls._write_to_log("S", message)

    @classmethod
    def info(cls, message: str):
        print(f"[{Logger._BOLD}{Logger._BLUE} I {Logger._RESET}] {message}")
        cls._write_to_log("I", message)

print(f"[{Logger._BOLD}{Logger._BLUE} I {Logger._RESET}] Logging started. Writing to \"logs/{_START_TIME}.log\"")
