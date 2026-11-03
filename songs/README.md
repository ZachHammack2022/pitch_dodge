# songs/

Every mp3, wav, ogg or flac file in this folder shows up in the game's song
list. Refresh the page after adding files.

Ways to add songs:

- Copy files in here yourself.
- Drag a file onto the game page while it's running.
- `.venv/bin/pitch-dodge fetch` downloads free recordings from the Internet
  Archive into this folder.
- `.venv/bin/pitch-dodge import-songs ~/some/folder` copies every song in
  another folder into here.

`CREDITS.md` lists where downloaded recordings came from and their licenses.
Keep it alongside the files if you share them.

To use a different folder, set `PITCH_DODGE_SONGS=/path/to/folder`.
