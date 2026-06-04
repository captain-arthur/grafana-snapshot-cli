from __future__ import annotations

import argparse

from cli.config import __version__
from services.snapshot import ExportParams, ImportParams, SnapshotService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="grafana-snapshots")
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"grafana-snapshots {__version__}",
    )

    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("export")
    export.add_argument("-n", "--name", required=True)
    export.add_argument("-f", "--from", dest="time_from", required=True)
    export.add_argument("-t", "--to", dest="time_to", required=True)
    export.add_argument("-d", "--directory", required=True)

    import_command = commands.add_parser("import")
    import_command.add_argument("-d", "--directory", required=True)

    return parser


def main() -> None:
    print(FLAG)

    args = build_parser().parse_args()
    service = SnapshotService()

    if args.command == "export":
        result = service.snapshot_export(
            ExportParams(
                name=args.name,
                directory=args.directory,
                time_from=args.time_from,
                time_to=args.time_to,
            )
        )
        print(result.model_dump_json())
        return

    if args.command == "import":
        result = service.snapshot_import(ImportParams(directory=args.directory))
        print(result.model_dump_json())


FLAG = f"""
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣤⣤⣤⣀⠀⠀⠀⠀⠀⠀⠀⣀⡀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣔⠉⣠⣿⣿⣿⠿⢿⣦⡀⠀⠀⠸⣿⣿⣥⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⢀⣴⣿⣿⣿⣿⣿⣿⣷⣀⣀⣿⣿⣦⡀⠀⠙⠃⠉⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⡔⠁⣿⣿⣿⡟⠉⢉⣻⣿⣿⣿⣿⣿⣿⡿⢆⠀⠀⠀⠀ "Just a moment, please..!"
⠀⠀⠀⠀⠀⠀⢷⣿⣿⣿⠟⠛⠋⠉⠉⠉⠙⠛⠿⣿⣿⡀⡸⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠈⠛⠿⡇⣠⠈⠓⢢⣦⡆⠚⠀⡄⢹⠿⠋⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⢾⣷⣴⣄⠀⢰⠀⠀⠀⠀⠘⠛⠀⠀⠀⠀⠈⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠸⣿⢿⣯⠁⠀⠘⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠈⠉⠀⠀⠀⠘⠠⣀⡀⠀⠀⠀⣀⡠⠔⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

"""

if __name__ == "__main__":
    main()
