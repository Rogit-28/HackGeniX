# Assets Directory

Place reference audio files here for TTS voice cloning.

## Expected Files

- **interviewer_voice.wav** — A 6-15 second WAV recording of the desired
  interviewer voice. Used by Coqui XTTS v2 for voice cloning.  If absent,
  XTTS falls back to its default speaker embedding.

### Requirements for Reference Audio

- **Format:** WAV (16-bit PCM)
- **Duration:** 6-15 seconds of clear speech
- **Quality:** Clean recording, minimal background noise
- **Content:** Any English speech (a few sentences is ideal)
