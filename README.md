# TagStock PhotoKey - Batch image processing for stock

Application for batch image processing with **AI content analysis** and automatic metadata generation for uploading to stock sites (Adobe Stock, Shutterstock, Getty Images, etc.).

## Features

### Quick Mode
- **AI content analysis of images** - the program analyzes what is shown in the photo and generates metadata based on the content
- **Local analysis without API** - uses pre-trained models (BLIP) for image analysis directly on your computer
- **External API support** - optionally use OpenAI API or custom API endpoint
- Automatic processing of all JPEG files and video clips (MOV, MP4, MPG) in the selected folder
- Video clips are checked against Adobe Stock technical requirements (see [Video](#video-adobe-stock))
- Metadata generation (title, description, keywords) following strict stock site rules
- **Direct metadata writing to image files** (EXIF/IPTC) - stock sites automatically pull data when uploading
- Files are copied to a second folder with written metadata

### Table Mode
- Manual metadata editing in table
- Load and save CSV files
- Add individual images
- Double-click to edit cells

## Installation and Launch

### First Launch

1. Create a virtual environment (if not already created):
```bash
python3 -m venv venv
```

2. Activate the virtual environment:
```bash
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

### Launching the Application

**Method 1: Via script (recommended)**
```bash
./run.sh
```

**Method 2: Manually**
```bash
source venv/bin/activate
python main.py
```

**Method 3: Direct launch (if virtual environment is already activated)**
```bash
python main.py
```

## Usage

### Quick Mode

1. Select folder with source JPEG files
2. Select folder for saving processed JPEG files
3. Enable option "Generate metadata (AI image analysis)"
4. **Select analysis type:**
   - **Local (no API)** - uses pre-trained models on your computer (recommended, no API keys required)
   - **OpenAI API** - uses OpenAI Vision API (requires API key)
   - **Custom API** - uses your own API endpoint
5. Click "Start processing"
6. After completion you will get:
   - **Processed JPEG files with written metadata** (title, description, keywords embedded in files via EXIF/IPTC)
   - Metadata is generated based on AI analysis of image content
   
**Important:** 
- Metadata is written directly to image files, so when uploading to stock sites they are automatically pulled into the required fields!
- **Local analysis works without internet and API keys** - model is downloaded once on first use (~990MB)
- OpenAI API requires a key (can be obtained at https://platform.openai.com/api-keys)

### Table Mode

1. Load existing CSV file or add images manually
2. Edit metadata by double-clicking cells
3. Save result to CSV file

## Video (Adobe Stock)

The input folder may also contain video clips (MOV, MP4, MPG). Before processing, each clip is checked
against the [Adobe Stock technical requirements for video](https://helpx.adobe.com/stock/contributor/submit-your-content/submit-videos/technical-requirements-for-video-submissions.html)
(`video_utils.py`). Clips that fail are **not copied** to the output folder; the reasons are listed in the log and in the final summary.

| Parameter | Requirement |
|---|---|
| Format | MOV, MPG, MP4 |
| Duration | 5-60 s (10-20 s recommended - warning only) |
| File size | up to 3900 MB |
| Frame rate | 23.976, 24, 25, 29.97, 30, 50, 59.94, 60 fps |
| Codec | ProRes, H.264 (recommended); MPEG-2, MPEG-4, Motion JPEG, PNG (accepted, warning) |
| Horizontal | 1920x1080, 2048x1080, 3840x2160, 4096x2160, 4096x2304; width 1920-4096 with wide-screen ratios (e.g. 2.39:1) |
| Vertical | 1080x1920, 2160x3840, 2160x4096, 2304x4096 |
| Square | 1080x1080, 2160x2160 |
| Audio (optional) | 48 kHz, 16-bit uncompressed PCM |

For clips that pass:
- 3 frames (at 25%, 50%, 75% of the clip) are sent to the AI as one video; metadata rules are the same as for photos
- vertical clips get the words `vertical` and `video` in the title and at the start of keywords (Adobe Stock rule)
- video files are **not copied and not modified** - the output folder gets only `adobe_stock_videos.csv` (Filename, Title, Keywords, Category, Releases)
- upload the clips to Adobe Stock Contributor, then in Uploaded Files > New click **Upload CSV**; filenames must match exactly (extension and case)

Video support requires **ffmpeg** (`brew install ffmpeg`).

## Metadata Format

### Metadata Generation Rules:

**Title:**
- English text only (a-z, A-Z, 0-9, spaces)
- No special characters
- Automatic formatting from filename

**Description:**
- One natural English sentence from the AI, without title words
- Does not share words with keywords
- 15-80 characters

**Keywords:**
- Up to 49 individual real words (Adobe Stock limit), no singular/plural duplicates
- English text only, no special characters
- Words separated by commas
- Not taken from title or description

### CSV Format

CSV file contains the following columns:
- `Filename` - source file name
- `Title` - image title
- `Description` - description
- `Keywords` - keywords (comma-separated)
- `Category` - category
- `Model Release` - model release availability (Yes/No)

## Technical Details

### Writing Metadata to Files

Metadata is written to image files via:
- **JPEG/JPG:** EXIF/IPTC metadata (via piexif)
  - Title → EXIF ImageDescription + IPTC ObjectName
  - Description → EXIF UserComment + IPTC Caption
  - Keywords → EXIF/IPTC Keywords
- **PNG/TIFF:** Metadata via Pillow

Stock sites (Adobe Stock, Shutterstock, Getty Images, etc.) automatically read this metadata when uploading.

## Requirements

- Python 3.8+
- PyQt6 for graphical interface
- Pillow for image processing
- piexif for writing EXIF/IPTC metadata to JPEG files
- transformers, torch for local AI image analysis (installed automatically)
- openai for AI analysis via OpenAI API (optional)
- httpx for working with custom APIs (optional)
- exiftool for writing IPTC metadata (installed automatically via brew)
- ffmpeg/ffprobe for video checks and frame extraction (`brew install ffmpeg`)

**Note:** On first launch of local analysis, the BLIP-2 model will be downloaded. This happens once.
- **BLIP-2 Flan-T5-Large** (Salesforce/blip2-flan-t5-large) - optimal balance of speed and quality
- Model size: ~2-3GB (downloaded automatically)
- Faster than XL version, but still provides very high quality and detailed descriptions

## Image Analysis Types

### Local Analysis (recommended)
- **No API keys required** - works completely offline
- Uses pre-trained model **BLIP-2 Flan-T5-Large** (Salesforce/blip2-flan-t5-large)
- Optimal balance of speed and description quality
- Model is downloaded automatically on first use (~2-3GB)
- Works on CPU (significantly faster on GPU with CUDA, if available)
- Recommended to use GPU for faster processing
- Free and unlimited
- **Improved prompts** - uses 8 different prompts to get maximally detailed descriptions
- **Extended generation parameters** - max_length=300, num_beams=7 for longer and higher quality descriptions

### OpenAI API
To use OpenAI API:

1. Get API key at https://platform.openai.com/api-keys
2. Select "OpenAI API" in the program
3. Enter key in "API Key" field - after "Start processing" it is saved to macOS Keychain (service "TagStock PhotoKey") and filled in automatically on next launch
4. Or set environment variable: `export OPENAI_API_KEY="sk-..."`

**Note:** AI analysis uses model `gpt-6-luna` (OpenAI GPT-6 Luna, vision support, `reasoning_effort="none"`). The model is set by `OPENAI_MODEL` in `main.py`. Price: $0.10 / 1M input tokens, $0.50 / 1M output tokens - approximately $0.30 per 1000 images.

### Custom API
- Select "Custom API" in the program
- Specify your API endpoint
- Enter API key (if required)
- API must accept requests in OpenAI-compatible format

## Notes

- Source files are not modified - processed files are copied to a second folder
- Metadata is generated based on AI analysis of image content
- **Local analysis is used by default** - no API keys required and works offline
- All metadata complies with stock site requirements (English text only, no special characters)
- Title, Description and Keywords are written to EXIF/IPTC metadata for automatic pulling on stock sites
- Local model is downloaded once on first use and cached for subsequent launches
