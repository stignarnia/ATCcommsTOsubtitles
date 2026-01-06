import argparse
from pathlib import Path

from ass_generator import generate_ass
from init_template import init_template
from burn import burn_from_ini

def main() -> None:
    parser = argparse.ArgumentParser(description="Compile comms INI to ASS, initialize template INI, or burn subtitles using ffmpeg (streams ASS).")
    parser.set_defaults(command="compile")
    subparsers = parser.add_subparsers(dest="command")

    # compile
    cp = subparsers.add_parser("compile", help="Compile INI to ASS")
    cp.add_argument("-i", "--input", default="../comms.ini", help="Input INI file (for compile)")
    cp.add_argument("-o", "--output", default="../comms.ass", help="Output ASS file (for compile)")

    # init
    ip = subparsers.add_parser("init", help="Initialize a template INI")
    ip.add_argument("--name", default="../comms.ini", help="Name for initialized INI file (for init)")

    # burn (new file, streams ASS to ffmpeg)
    bp = subparsers.add_parser("burn", help="Burn subtitles into video or produce transparent overlay (requires ffmpeg)")
    bp.add_argument("--mode", choices=["default", "trim", "transparent"], default="default", help="Burn mode (see readme)")
    bp.add_argument("-i", "--input", default="../comms.ini", help="Input INI file (used to generate ASS)")
    bp.add_argument("-v", "--video", help="Input video file (required for default and trim modes)")
    bp.add_argument("-o", "--output", default="../output", help="Output file path with no extension")
    bp.add_argument("--progress", default="true", choices=["true", "false"], help="Show progress bar (true/false). Use 'false' to keep ffmpeg output.")

    args = parser.parse_args()

    if args.command == "init":
        init_template(args.name)
    elif args.command == "burn":
        ini_path = Path(args.input)
        video_path = Path(args.video) if args.video else None
        out_path = Path(args.output)
        progress = True if args.progress.lower() == "true" else False
        burn_from_ini(args.mode, ini_path, video_path, out_path, progress)
    else:
        # compile (default)
        generate_ass(args.input, args.output)

if __name__ == "__main__":
    main()
