import argparse

from ass_generator import generate_ass
from init_template import init_template

def main() -> None:
    parser = argparse.ArgumentParser(description="Compile comms INI to ASS or initialize a template INI.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["compile", "init"],
        default="compile",
        help="Command to run (default: compile)",
    )
    parser.add_argument("-i", "--input", default="../comms.ini", help="Input INI file (for compile)")
    parser.add_argument("-o", "--output", default="../comms.ass", help="Output ASS file (for compile)")
    parser.add_argument("--name", default="../comms.ini", help="Name for initialized INI file (for init)")

    args = parser.parse_args()

    if args.command == "init":
        init_template(args.name)
    else:
        # compile (default)
        generate_ass(args.input, args.output)

if __name__ == "__main__":
    main()
