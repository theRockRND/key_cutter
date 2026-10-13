# Changelog

## 1.1.3

### Added
- The log of every run is saved to `logs/run_YYYY-MM-DD_HH-MM-SS.log` next to `main.py` (also when the run is stopped or fails). The path is shown at the start and end of the log and in the completion message

### Fixed
- Title keeps linking words between content words: "Railway Tracks and White Car Through Pine Forest" instead of "Railway Tracks White Car Through Pine Forest". Articles are still dropped, linking words never start or end a title. Linking words (and, in, through, toward...) are not title words: the description may use them, keywords never do
- Description is no longer broken by cutting words out of the middle ("dim passage a sunlit forest"): the AI gets up to 3 rewrite attempts, each told what was wrong; if none is clean, the sentence is cut before the first forbidden word
- A description that is too long is cut before the last unfinished phrase ("...through sunny woods" instead of "...through sunny woods and rocky")
- Hyphens, dashes and slashes become spaces: "forward facing" instead of "forwardfacing"
- A short title is not padded with a singular/plural duplicate of its own word (Stick / Sticks)

## 1.1.2

### Added
- Unit tests (`tests/`, stdlib `unittest`, no extra dependencies): Adobe Stock video requirements, ffprobe/frame extraction on generated clips, metadata rules (title/description/keywords, vertical video), OpenAI request handling (JSON mode, retries, fatal errors) with a fake client, description rewrite, Keychain storage, end-to-end batch processing. Run with `python -m unittest discover -s tests -t .`

## 1.1.1

### Fixed
- Requests use JSON mode (`response_format`) and are retried once on invalid JSON or a temporary API error
- One failed file no longer stops the batch: it is skipped and listed at the end. Only key or balance errors stop processing
- A description longer than 80 characters is rewritten by the AI instead of being cut off; the rewrite gets the full list of forbidden words and a second attempt
- A short title is padded with AI keywords, not with description words

## 1.1.0

### Added
- Video support (MOV, MP4, MPG): each clip is checked against the Adobe Stock technical requirements for video (format, 5-60 s duration, 3900 MB limit, frame rate, codec, resolution, 48 kHz 16-bit PCM audio). Clips that fail are skipped, with the reasons listed in the log
- Video analysis: 3 frames from the clip are sent to the AI as one video
- Vertical clips get "Vertical Video" in the title and "vertical, video" at the start of the keywords
- `adobe_stock_videos.csv` is written to the output folder for the Adobe Stock CSV upload. Video files are not copied or modified
- The last used API key is saved to macOS Keychain and filled in on the next launch
- Version number shown in the window title

### Changed
- Model switched from `gpt-5.1` to `gpt-6-luna` (`reasoning_effort="none"`)
- Keywords: up to 49 (the Adobe Stock limit), only real words from the AI, no generated variations and no singular/plural duplicates. The AI is asked for 65 words so enough remain after filtering
- Description: a natural sentence from the AI. If it uses title words, the AI is asked to rewrite it
- File search is case-insensitive without duplicates on macOS

### Security
- Removed the hardcoded OpenAI API key. The key now comes from the UI field, the Keychain or `OPENAI_API_KEY`
