import pathlib

import typer

from moviepy import AudioFileClip
from pathlib import Path

app = typer.Typer()


@app.command()
def main(video: pathlib.Path, songs: pathlib.Path):
    print(f"Songs folder {songs}")
    song_files = Path(songs).glob("*.mp4")
    for song_file in song_files:
        # print(f"Processing {song_file}")
        audio_clip = AudioFileClip(str(song_file))
        print(f"Length of {song_file} is {audio_clip.duration} seconds")
    pass

if __name__ == "__main__":
    app()