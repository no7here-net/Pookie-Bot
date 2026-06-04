# Handles terminal printing and colouring
# E = error
# W = warning
# S = success
# I = info
# O = output (actual error output)

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

        with open("..output.log", "a", encoding="utf-8") as f:
            f.write(f"[ {timestamp} ] [ {label} ] {message}\n")

    @classmethod
    def error(message: str, output: str = None):
        print(f"[{Logger._BOLD}{Logger._RED} E {Logger.RESET}] {message}")
        cls._write_to_file("E", message)

        if output != None:
            cls._write_to_file("O", message)

    @classmethod
    def warning(message: str):
        print(f"[{Logger._BOLD}{Logger._RED} W {Logger.RESET}] {message}")
        cls._write_to_file("W", message)

    @classmethod
    def success(message: str):
        print(f"[{Logger._BOLD}{Logger._RED} S {Logger.RESET}] {message}")
        cls._write_to_file("S", message)

    @classmethod
    def info(message: str):
        print(f"[{Logger._BOLD}{Logger._RED} I {Logger.RESET}] {message}")
        cls._write_to_file("I", message)
