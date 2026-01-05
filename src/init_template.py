import os


def init_template(name: str = "comms.ini") -> None:
    """Create a starter INI file at `name` if it doesn't exist."""
    if os.path.exists(name):
        print(f"File already exists: {name}")
        return

    sample = """; Meta types
[metaTypes.Timestamp]
; Every combination of hours, minutes, seconds and milliseconds is supported for *input parsing*.
; Important: ASS/SSA event timestamps are centiseconds (H:MM:SS.cc), not milliseconds. If an ASS file
; uses ".mmm", VLC/libass can treat that suffix as centiseconds and display events overlapping.
; This project therefore writes centisecond-precision timestamps to the output ASS.
format = mm:ss
; Characters-per-second used for subtitle duration estimation when fitting lines between T markers
cps = 15

[metaTypes.Comment]
position = top-left
color = gray
background = none

; Speaker types
[speakerTypes.ATC]
position = bottom-left
color = white
background = none

[speakerTypes.Pilot]
position = bottom-right
color = cyan
background = none

; Meta tags
[meta.T]
type = Timestamp

[meta.C]
type = Comment

; Speakers
[speakers.APP]
name = Lisboa Approach
type = ATC

[speakers.LH]
name = DLH97V
type = Pilot
color = blue

; Acronyms
[acronyms.FL]
extension = Flight Level

; Waypoints
[waypoints.RNAV]
LAZET

; Comms
; Special characters like the ' in don't should be escaped by wrapping the string in double quotes ("). These will not be rendered in the subtitles
[comms]
T = 00:00
C = Time: 18:50 UTC on December 30, 2025, ATIS K in effect, QNH 1020 hPa
LH = Lisboa Arrival good evening, DLH97V, FL350, inbound to INBOM, Information K
"""

    with open(name, "w", encoding="utf-8") as f:
        f.write(sample)
    print(f"Wrote template INI to {name}")
