"""Pomocniczy uruchamiacz istniejacych skryptow, z haslem przekazanym przez stdin.
Uruchamiany przez main_gui_full.py w Pythonie projektu (.venv), nie w QGIS.
"""
import getpass
import runpy
import sys


def password_from_stdin(prompt="Haslo: ", stream=None):
    password = sys.stdin.readline()
    if not password:
        raise RuntimeError("Nie przekazano hasla PostgreSQL")
    return password.rstrip("\r\n")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uzycie: run_psip_job.py skrypt.py [argumenty]")
    script = sys.argv[1]
    arguments = sys.argv[2:]
    getpass.getpass = password_from_stdin
    sys.argv = [script] + arguments
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
