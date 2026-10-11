import sys
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QLineEdit, QTextEdit, QProgressBar,
                             QCheckBox, QTableWidget, QTableWidgetItem,
                             QFileDialog, QMessageBox, QGroupBox, QHeaderView, QDialog,
                             QDialogButtonBox, QComboBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon
from pathlib import Path
import csv
import re
import shutil
import subprocess
import base64
import json
import httpx
import time
import tempfile
from datetime import datetime
from PIL import Image
import piexif
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

class FatalAPIError(Exception):
    """API error that makes further processing pointless (wrong key, no quota)"""


def is_fatal_api_error(error_str):
    markers = ["401", "invalid_api_key", "Incorrect API key", "insufficient_quota", "403", "model_not_found"]
    return any(marker in error_str for marker in markers)


# Last used API key is stored in system keychain (macOS Keychain)
KEYRING_SERVICE = 'TagStock PhotoKey'
KEYRING_USER = 'openai_api_key'


def load_saved_api_key():
    """Returns API key saved in keychain or None"""
    if not KEYRING_AVAILABLE:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception as e:
        print(f"Failed to read API key from keychain: {e}")
        return None


def save_api_key(api_key):
    """Saves API key to keychain. Returns True on success"""
    if not KEYRING_AVAILABLE:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, api_key)
        return True
    except Exception as e:
        print(f"Failed to save API key to keychain: {e}")
        return False

__version__ = "1.1.2"

# Local models removed - using only OpenAI API

from video_utils import (VIDEO_EXTENSIONS, is_video_file, probe_video, check_video_requirements,
                         get_orientation, extract_frames)

ANALYSIS_PROMPT = """Analyze this image carefully and describe what you see. Then provide metadata for stock photography.

IMPORTANT: Look at the image and describe what is actually shown - the main subject, objects, animals, people, scenery, colors, actions, etc.

Return ONLY a JSON object with this exact structure (no markdown, no code blocks):
{
  "title": "descriptive title based on what you see in the image, English only, no special characters",
  "description": "one natural English sentence about the image, 40-80 characters, no special characters",
  "keywords": "comma-separated list of 65 individual words describing the image content, English only, no special characters, only single words not phrases"
}

CRITICAL RULES:
- Title: Describe the main subject/scene with 6 to 10 WORDS (e.g. "Deer Grazing On Green Grass In Field", "Sunset Over Mountains With Clouds"). Only English letters and spaces, no special characters.
- Description: ONE natural, grammatical sentence (e.g. "Young animal pauses near a wooden fence on a quiet summer morning"). 40-80 characters, English only, no special characters. It must NOT reuse any word from the title and should avoid words from the keywords - use synonyms instead.
- Keywords: List 65 individual REAL English words separated by commas (e.g. "deer, wildlife, nature, grass, animal, mammal, forest, outdoor, wild, grazing, brown, green, fence, trees, sky, sunny, natural, habitat"). Most relevant words first. Describe the main subject, objects, colors, textures, actions, environment, mood, season, time of day, weather, concepts. Only single words, no phrases, no invented words, no plural/singular duplicates of the same word, English only.

Analyze the image NOW and return ONLY the JSON object."""

# OpenAI model for image/video analysis
OPENAI_MODEL = 'gpt-6-luna'

VIDEO_CSV_NAME = 'adobe_stock_videos.csv'

# Adobe Stock accepts up to 49 keywords
MAX_KEYWORDS = 49
MIN_KEYWORDS = 25  # below this a warning is logged

# Stop words: never used in title or keywords
STOP_WORDS = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "with", "is", "are", "was", "were",
    "and", "or", "but", "this", "that", "these", "those", "it", "its", "they", "them", "what", "you",
    "by", "from", "as", "be", "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "up", "out", "so", "if", "no", "not", "only", "just",
    "more", "most", "very", "much", "many", "some", "any", "all", "each", "every", "both", "such",
    "than", "too", "also", "here", "there", "where", "when", "why", "how", "who", "which", "whose", "whom",
    "see", "image", "photography", "photo", "picture", "detailed", "describe", "scene", "happening",
    "showing", "view", "professional", "high", "quality"
}

# Generic words removed from description phrase (articles and prepositions are kept for grammar)
DESCRIPTION_BANNED_WORDS = {
    "see", "image", "photography", "photo", "picture", "detailed", "describe", "scene", "happening",
    "showing", "view", "professional", "high", "quality", "list", "main", "objects", "colors", "elements"
}

# Words that may not end a truncated description
DESCRIPTION_TRAILING_WORDS = STOP_WORDS | {"between", "under", "over", "near", "into", "through", "across",
                                           "behind", "along", "around", "against", "beside", "below", "above"}

VIDEO_PROMPT_INTRO = """The {count} images below are frames taken from the beginning, middle and end of ONE stock video clip. Treat them as a single video: describe the subject, action and motion over time, not separate photos.

"""


class ProcessingThread(QThread):
    """Thread for processing images"""
    progress = pyqtSignal(int, int)  # current, total
    log_message = pyqtSignal(str)
    finished = pyqtSignal(list)  # list of data for CSV
    
    def __init__(self, input_folder, output_folder, generate_metadata=True, api_key=None):
        super().__init__()
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.generate_metadata = generate_metadata  # Enabled by default
        # API key from UI field, otherwise OPENAI_API_KEY environment variable
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        self.previous_titles = set()  # Track previous titles to avoid duplicates
        self.previous_descriptions = set()  # Track previous descriptions
        self._stop_requested = False  # Flag for stopping processing
    
    def stop(self):
        """Stops processing"""
        self._stop_requested = True
        self.log_message.emit("Stopping processing...")
        
    def run(self):
        self._stop_requested = False  # Reset stop flag on start
        self.log_message.emit("=" * 80)
        self.log_message.emit("[Processing] Starting processing...")
        self.log_message.emit(f"[Processing] Input folder: {self.input_folder}")
        self.log_message.emit(f"[Processing] Output folder: {self.output_folder}")
        self.log_message.emit(f"[Processing] Generate metadata: {self.generate_metadata}")
        self.log_message.emit(f"[Processing] Using OpenAI API (GPT)")
        
        # Find JPEG and video files (suffix check is case-insensitive, no duplicates on macOS)
        image_extensions = ['.jpg', '.jpeg']
        
        self.log_message.emit(f"[Processing] Searching for JPEG and video files in folder: {self.input_folder}")
        all_files = sorted(p for p in Path(self.input_folder).iterdir() if p.is_file())
        image_files = [p for p in all_files if p.suffix.lower() in image_extensions + VIDEO_EXTENSIONS]
        video_count = sum(1 for p in image_files if is_video_file(p))
        
        total = len(image_files)
        self.log_message.emit(f"[Processing] Files found: {total - video_count} JPEG, {video_count} video ({', '.join(VIDEO_EXTENSIONS)})")
        
        if total == 0:
            self.log_message.emit("[Processing] ERROR: JPEG or video files not found!")
            self.finished.emit([])
            return
        
        # Create output folder if it doesn't exist
        self.log_message.emit(f"[Processing] Creating output folder (if not exists): {self.output_folder}")
        Path(self.output_folder).mkdir(parents=True, exist_ok=True)
        self.log_message.emit(f"[Processing] Output folder ready")
        
        processed_count = 0
        rejected_videos = []  # (filename, [reasons]) - videos not meeting Adobe Stock requirements
        self._video_csv_started = False  # Adobe Stock CSV is recreated on each run
        failed_files = []  # (filename, error) - files skipped because metadata generation failed
        self.log_message.emit(f"[Processing] Starting processing of {total} files...")
        
        for idx, image_path in enumerate(image_files, 1):
            # Check for stop request
            if self._stop_requested:
                self.log_message.emit("[Processing] Processing stopped by user")
                self.log_message.emit(f"[Processing] Processed files: {processed_count} of {total}")
                self.finished.emit([])
                return
            
            try:
                self.log_message.emit(f"[Processing] Processing {idx}/{total}: {image_path.name}")
                self.log_message.emit(f"[Processing] File size: {image_path.stat().st_size / 1024:.2f} KB")
                
                # Video: check Adobe Stock technical requirements before processing
                video_info = None
                if is_video_file(image_path):
                    video_info, errors = self.check_video(image_path)
                    if errors:
                        rejected_videos.append((image_path.name, errors))
                        self.progress.emit(idx, total)
                        continue
                
                if video_info:
                    # Video is not modified, so it is not copied: metadata goes to Adobe Stock CSV only
                    output_file_path = image_path
                else:
                    # Copy file to output folder
                    output_file_path = Path(self.output_folder) / image_path.name
                    self.log_message.emit(f"[Processing] Copying file to: {output_file_path}")
                    shutil.copy2(image_path, output_file_path)
                    self.log_message.emit(f"  ✓ File copied to output folder")
                
                # Check for stop request before analysis
                if self._stop_requested:
                    self.log_message.emit("[Processing] Processing stopped by user")
                    self.log_message.emit(f"[Processing] Processed files: {processed_count} of {total}")
                    self.finished.emit([])
                    return
                
                # Analyze file and generate metadata
                metadata = {}
                if self.generate_metadata:
                    # Small delay between requests to avoid rate limits (0.5 sec)
                    if idx > 1:
                        time.sleep(0.5)
                    
                    self.log_message.emit(f"[Processing] Generating metadata for file {idx}/{total}...")
                    try:
                        metadata = self.analyze_and_generate_metadata(output_file_path, video_info)
                        self.log_message.emit(f"[Processing] Metadata successfully generated for file {idx}/{total}")
                    except FatalAPIError as e:
                        # Wrong key / no quota: stop, other files would fail the same way
                        self.log_message.emit(f"    ❌ [Processing] CRITICAL ERROR: {str(e)}")
                        self.log_message.emit("[Processing] Processing stopped: check API key and balance")
                        self.log_message.emit(f"[Processing] Processed files: {processed_count} of {total}")
                        self.finished.emit([])
                        return
                    except Exception as e:
                        # Error for this file only: skip it and continue with others
                        self.log_message.emit(f"    ❌ [Processing] Failed to generate metadata for {image_path.name}: {str(e)}")
                        failed_files.append((image_path.name, str(e)))
                        if not video_info and output_file_path.exists():
                            output_file_path.unlink()  # do not leave a photo copy without metadata
                        self.progress.emit(idx, total)
                        continue
                    
                    # Check for stop request after analysis
                    if self._stop_requested:
                        self.log_message.emit("[Processing] Processing stopped by user")
                        self.log_message.emit(f"[Processing] Processed files: {processed_count} of {total}")
                        self.finished.emit([])
                        return
                    
                    self.log_message.emit(f"  ✓ Metadata generated:")
                    self.log_message.emit(f"    Title: {metadata.get('title', '')}")
                    self.log_message.emit(f"    Description: {metadata.get('description', '')}")
                    keywords_preview = metadata.get('keywords', '')
                    keywords_count = len(keywords_preview.split(',')) if keywords_preview else 0
                    self.log_message.emit(f"    Keywords: {keywords_preview[:50]}... ({keywords_count} words)")
                    
                    # Write metadata to copied file
                    try:
                        self.log_message.emit(f"[Processing] Writing metadata to file {idx}/{total}...")
                        if video_info:
                            self.write_video_csv_row(output_file_path.name, metadata)
                        else:
                            self.write_metadata_to_image(output_file_path, metadata)
                        self.log_message.emit(f"  ✓ Metadata written to file")
                    except Exception as e:
                        self.log_message.emit(f"  ⚠ [Processing] Error writing metadata: {str(e)}")
                        import traceback
                        self.log_message.emit(f"  [Processing] Write error details: {traceback.format_exc()}")
                else:
                    self.log_message.emit(f"[Processing] Metadata generation disabled, skipping")
                
                processed_count += 1
                self.progress.emit(idx, total)
                self.log_message.emit(f"[Processing] File {idx}/{total} processed successfully")
                
            except Exception as e:
                self.log_message.emit(f"  ✗ [Processing] Error processing {image_path.name}: {str(e)}")
                import traceback
                self.log_message.emit(f"  [Processing] Error details: {traceback.format_exc()}")
        
        if not self._stop_requested:
            self.log_message.emit("=" * 80)
            self.log_message.emit("[Processing] Processing completed!")
            self.log_message.emit(f"[Processing] Processed files: {processed_count} of {total}")
            self.log_message.emit(f"[Processing] Results saved to: {self.output_folder}")
            if self._video_csv_started:
                self.log_message.emit(f"[Processing] Video metadata CSV for Adobe Stock: {Path(self.output_folder) / VIDEO_CSV_NAME}")
            if failed_files:
                self.log_message.emit(f"[Processing] ⚠ Files skipped (metadata generation failed, run again to retry): {len(failed_files)}")
                for name, error in failed_files:
                    self.log_message.emit(f"    ✗ {name}: {error}")
            if rejected_videos:
                self.log_message.emit(f"[Processing] ⚠ Videos skipped (do not meet Adobe Stock requirements): {len(rejected_videos)}")
                for name, reasons in rejected_videos:
                    self.log_message.emit(f"    ✗ {name}: {'; '.join(reasons)}")
            self.log_message.emit("=" * 80)
        else:
            self.log_message.emit("[Processing] Processing was stopped by user")
        
        self.finished.emit([])
    
    def check_video(self, video_path):
        """Checks video against Adobe Stock technical requirements. Returns (video_info, errors)"""
        self.log_message.emit(f"[Video] Checking Adobe Stock technical requirements...")
        try:
            info = probe_video(video_path)
        except FileNotFoundError:
            return None, ["ffprobe not found. Install: brew install ffmpeg"]
        except Exception as e:
            return None, [f"cannot read video: {str(e)}"]
        
        audio = info['audio']
        audio_text = f"{audio['codec']} {audio['sample_rate']} Hz" if audio else "no audio"
        fps_text = f"{info['fps']:.3f}" if info['fps'] else "?"
        duration_text = f"{info['duration']:.2f}s" if info['duration'] is not None else "?"
        self.log_message.emit(f"[Video] {info['width']}x{info['height']}, {fps_text} fps, {info['codec']}, "
                              f"{duration_text}, {info['size_mb']:.1f} MB, {audio_text}")
        
        errors, warnings = check_video_requirements(info, video_path.suffix)
        for warning in warnings:
            self.log_message.emit(f"  ⚠ [Video] {warning}")
        if errors:
            for error in errors:
                self.log_message.emit(f"  ✗ [Video] {error}")
            self.log_message.emit(f"  ✗ [Video] Skipped: does not meet Adobe Stock requirements")
        else:
            self.log_message.emit(f"  ✓ [Video] Meets Adobe Stock technical requirements")
        return info, errors
    
    def clean_text(self, text):
        """Cleans text from special characters, keeps only English letters, numbers and spaces"""
        # Keep only English letters, numbers and spaces
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', text)
        # Remove multiple spaces
        cleaned = ' '.join(cleaned.split())
        return cleaned
    
    def clean_caption_from_prompts(self, caption):
        """Removes all prompts from caption"""
        prompts_to_remove = [
            "describe what you see in detail:",
            "what is happening in this image:",
            "describe the image in detail including all objects, colors, and details:",
            "what objects, animals, people, and details are visible in this image:",
            "describe the scene, environment, background, and foreground in detail:",
            "list all visible objects, colors, textures, and details:",
            "describe the main subject and all surrounding elements:",
            "what can you see in this photograph, describe everything in detail:",
            # Old prompts for compatibility
            "describe what you see:",
            "what is happening:",
            "describe the image in detail:",
            "what objects and details are visible:",
            "describe the scene and environment:"
        ]
        cleaned = caption
        for prompt in prompts_to_remove:
            cleaned = cleaned.replace(prompt, "")
        return cleaned.strip()
    
    def extract_words(self, text, max_words=50):
        """Extracts individual words from text (not phrases)"""
        # Clean from special characters
        cleaned = self.clean_text(text)
        # Split into words
        words = cleaned.lower().split()
        # Remove duplicates, preserving order
        unique_words = []
        seen = set()
        for word in words:
            if word not in seen and len(word) > 0:
                unique_words.append(word)
                seen.add(word)
                if len(unique_words) >= max_words:
                    break
        return ', '.join(unique_words)
    
    def analyze_image_with_ai(self, image_path, video_info=None):
        """Analyzes image (or video frames) content through OpenAI GPT API"""
        self.log_message.emit(f"    [AI] Starting image analysis through OpenAI GPT API...")
        
        # API analysis
        api_key = self.api_key or os.getenv('OPENAI_API_KEY')
        if not api_key:
            error_msg = "ERROR: API key not specified. Processing stopped."
            self.log_message.emit(f"    ❌ {error_msg}")
            raise Exception(error_msg)
        
        self.log_message.emit(f"    [AI] API key found, length: {len(api_key)} characters")
        
        # OpenAI API
        self.log_message.emit(f"    [AI] Using OpenAI GPT API")
        if video_info is not None:
            # Video: analyze several frames extracted from the clip
            with tempfile.TemporaryDirectory() as frames_dir:
                frames = extract_frames(image_path, frames_dir, video_info['duration'])
                self.log_message.emit(f"    [AI] Extracted {len(frames)} frames from video")
                if not frames:
                    raise Exception("ERROR: Failed to extract frames from video (check ffmpeg)")
                result = self._analyze_with_openai_api(frames, api_key, is_video=True)
        else:
            result = self._analyze_with_openai_api([image_path], api_key)
        if result is None:
            error_msg = "ERROR: No valid response from AI after 2 attempts (see log above)"
            self.log_message.emit(f"    ❌ {error_msg}")
            raise Exception(error_msg)
        self.log_message.emit(f"    [AI] OpenAI GPT API returned result: title={result.get('title', '')[:30] if result else 'None'}...")
        return result
    
    def _build_messages(self, images_data, is_video=False):
        """Builds OpenAI request messages for one image or several video frames"""
        prompt = ANALYSIS_PROMPT
        if is_video:
            prompt = VIDEO_PROMPT_INTRO.format(count=len(images_data)) + prompt.replace(
                "stock photography", "stock video footage")
        content = [{"type": "text", "text": prompt}]
        for image_data in images_data:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_data}"
                }
            })
        return [{"role": "user", "content": content}]
    
    def _analyze_with_openai_api(self, image_paths, api_key, is_video=False):
        """Analysis through OpenAI API"""
        self.log_message.emit(f"    [OpenAI] Starting analysis through OpenAI API...")
        
        if not OPENAI_AVAILABLE:
            error_msg = "ERROR: OpenAI not installed. Install: pip install openai"
            self.log_message.emit(f"    ❌ {error_msg}")
            raise Exception(error_msg)
        
        try:
            self.log_message.emit(f"    [OpenAI] Opening and encoding image...")
            # Open and encode images (one photo or several video frames)
            images_data = []
            for image_path in image_paths:
                with open(image_path, 'rb') as image_file:
                    images_data.append(base64.b64encode(image_file.read()).decode('utf-8'))
            
            self.log_message.emit(f"    [OpenAI] Encoded {len(images_data)} image(s), size: {sum(len(d) for d in images_data)} characters")
            
            # Use standard OpenAI endpoint
            self.log_message.emit(f"    [OpenAI] Using standard OpenAI endpoint")
            client = OpenAI(api_key=api_key)
            messages = self._build_messages(images_data, is_video)
        except Exception as e:
            self.log_message.emit(f"    ❌ Error preparing request: {str(e)}")
            return None
        
        # Two attempts: retry on invalid JSON, rate limit or temporary API error
        for attempt in (1, 2):
            try:
                self.log_message.emit(f"    [OpenAI] Sending request to API (model: {OPENAI_MODEL}, attempt {attempt}/2)...")
                response = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    reasoning_effort="none",  # temperature is rejected when reasoning is on
                    messages=messages,
                    response_format={"type": "json_object"},  # guarantees valid JSON
                    max_completion_tokens=1500,  # Enough for complete JSON with 65 keywords
                    temperature=0.3
                )
            except Exception as e:
                error_str = str(e)
                if is_fatal_api_error(error_str):
                    # Wrong key or no money: other files will fail the same way
                    raise FatalAPIError(f"OpenAI API error: {error_str[:300]}")
                self.log_message.emit(f"    ⚠ [OpenAI] Request error: {error_str[:300]}")
                if attempt == 1:
                    if "rate limit" in error_str.lower() or "429" in error_str:
                        self.log_message.emit(f"    ⚠ Rate limit reached, waiting 60 seconds...")
                        time.sleep(60)
                    continue
                return None
            
            self.log_message.emit(f"    [OpenAI] Response received from API")
            content = (response.choices[0].message.content or '').strip()
            self.log_message.emit(f"    [OpenAI] AI response received, length: {len(content)} characters")
            result = self._parse_ai_response(content)
            if result:
                return result
            if attempt == 1:
                self.log_message.emit(f"    ⚠ [OpenAI] Invalid JSON in AI response, retrying...")
        return None
    
    def _rewrite_description(self, description, forbidden_words):
        """Text-only request: rewrites description without forbidden words. Returns None on failure"""
        if not OPENAI_AVAILABLE or not self.api_key:
            return None
        prompt = (f"Rewrite this stock footage description as ONE natural, grammatical English sentence, "
                  f"40-80 characters, no special characters. Keep the meaning. "
                  f"Do NOT use any of these words or their forms: {', '.join(forbidden_words)}.\n\n"
                  f"Sentence: {description}\n\nReturn ONLY the new sentence.")
        rewritten = None
        try:
            client = OpenAI(api_key=self.api_key)
            # Second attempt only if the first rewrite still uses forbidden words
            for attempt in (1, 2):
                response = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    reasoning_effort="none",
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=100,
                    temperature=0.3 if attempt == 1 else 0.7
                )
                rewritten = self.clean_text(response.choices[0].message.content or '') or rewritten
                used = set(self.normalize_words(rewritten or '')) & set(forbidden_words)
                too_long = len(rewritten or '') > 80
                if not used and not too_long:
                    return rewritten
                problems = []
                if used:
                    problems.append(f"still uses {sorted(used)}")
                if too_long:
                    problems.append(f"is {len(rewritten)} characters")
                self.log_message.emit(f"    [Metadata] Rewritten description {' and '.join(problems)}" +
                                      (", retrying..." if attempt == 1 else ", fixing it in code"))
            return rewritten
        except Exception as e:
            self.log_message.emit(f"    ⚠ [Metadata] Description rewrite failed: {str(e)}")
            return rewritten
    
    def _parse_ai_response(self, content):
        """Parses AI response and extracts metadata"""
        self.log_message.emit(f"    [Parser] Starting parsing of AI response, length: {len(content)} characters")
        
        # Strategy 1: Try to parse entire response as JSON
        try:
            metadata = json.loads(content.strip())
            self.log_message.emit(f"    [Parser] Entire response parsed as JSON: title={metadata.get('title', '')[:30] if metadata.get('title') else 'None'}..., keywords_count={len(metadata.get('keywords', '').split(',')) if metadata.get('keywords') else 0}")
            return metadata
        except json.JSONDecodeError:
            pass
        
        # Strategy 2: Search for JSON in markdown code blocks (```json ... ```)
        json_code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_code_block:
            try:
                self.log_message.emit(f"    [Parser] JSON found in markdown block, parsing...")
                metadata = json.loads(json_code_block.group(1))
                self.log_message.emit(f"    [Parser] JSON parsed successfully: title={metadata.get('title', '')[:30] if metadata.get('title') else 'None'}..., keywords_count={len(metadata.get('keywords', '').split(',')) if metadata.get('keywords') else 0}")
                return metadata
            except json.JSONDecodeError as e:
                self.log_message.emit(f"    [Parser] Error parsing JSON from markdown block: {str(e)}")
        
        # Strategy 3: Search for JSON object using more reliable regex
        # Search for opening brace and try to find corresponding closing brace
        start_pos = content.find('{')
        if start_pos != -1:
            # Start with opening brace and search for corresponding closing brace
            brace_count = 0
            end_pos = start_pos
            in_string = False
            escape_next = False
            
            for i in range(start_pos, len(content)):
                char = content[i]
                
                if escape_next:
                    escape_next = False
                    continue
                
                if char == '\\':
                    escape_next = True
                    continue
                
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end_pos = i + 1
                            break
            
            # If closing brace not found, take all remaining text
            if brace_count > 0:
                end_pos = len(content)
            
            # If full JSON found (brace_count == 0) or truncated (brace_count > 0)
            if end_pos > start_pos:
                json_str = content[start_pos:end_pos]
                try:
                    self.log_message.emit(f"    [Parser] JSON found in response (position {start_pos}-{end_pos}), parsing...")
                    metadata = json.loads(json_str)
                    self.log_message.emit(f"    [Parser] JSON parsed successfully: title={metadata.get('title', '')[:30] if metadata.get('title') else 'None'}..., keywords_count={len(metadata.get('keywords', '').split(',')) if metadata.get('keywords') else 0}")
                    return metadata
                except json.JSONDecodeError as e:
                    self.log_message.emit(f"    [Parser] Error parsing JSON: {str(e)}")
                    # If JSON is truncated (missing closing braces) or cannot be parsed
                    # Try to restore it
                    if brace_count > 0 or '"keywords"' in json_str:
                        self.log_message.emit(f"    [Parser] JSON truncated (missing {brace_count} closing braces), trying to restore...")
                        # Trying to restore truncated JSON
                        json_str_fixed = json_str
                        
                        # If keywords are truncated, truncate them to last complete comma
                        if '"keywords"' in json_str_fixed:
                            keywords_start = json_str_fixed.find('"keywords"')
                            if keywords_start != -1:
                                # Find start of keywords value (after ": ")
                                colon_pos = json_str_fixed.find(':', keywords_start)
                                if colon_pos != -1:
                                    # Skip spaces after colon
                                    value_start = colon_pos + 1
                                    while value_start < len(json_str_fixed) and json_str_fixed[value_start] in ' \n\t':
                                        value_start += 1
                                    
                                    # If value starts with quote
                                    if value_start < len(json_str_fixed) and json_str_fixed[value_start] == '"':
                                        value_start += 1  # Skip opening quote
                                        
                                        # Find last comma in keywords (but not at the end)
                                        keywords_value = json_str_fixed[value_start:]
                                        # Search for last comma followed by at least one character
                                        last_comma = -1
                                        for i in range(len(keywords_value) - 1, -1, -1):
                                            if keywords_value[i] == ',':
                                                # Check that there is at least one character after comma
                                                if i + 1 < len(keywords_value) and keywords_value[i+1] not in ' \n\t"':
                                                    last_comma = i
                                                    break
                                        
                                        if last_comma > 0:
                                            # Truncate keywords to last comma and close quote
                                            json_str_fixed = json_str_fixed[:value_start + last_comma] + '"'
                                            self.log_message.emit(f"    [Parser] Keywords truncated to last complete comma")
                        
                        # Close JSON properly
                        json_str_fixed += '}'
                        
                        try:
                            metadata = json.loads(json_str_fixed)
                            self.log_message.emit(f"    [Parser] JSON restored and parsed: title={metadata.get('title', '')[:30] if metadata.get('title') else 'None'}..., keywords_count={len(metadata.get('keywords', '').split(',')) if metadata.get('keywords') else 0}")
                            return metadata
                        except json.JSONDecodeError as e2:
                            self.log_message.emit(f"    [Parser] Failed to restore JSON: {str(e2)}")
                            self.log_message.emit(f"    [Parser] Restoration attempt (first 300 characters): {json_str_fixed[:300]}")
                    
                    self.log_message.emit(f"    [Parser] JSON content (first 500 characters): {json_str[:500]}")
        
        # Strategy 4: Try to find JSON using greedy search (old method, but with improvements)
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
        if json_match:
            try:
                self.log_message.emit(f"    [Parser] JSON found by greedy search, parsing...")
                metadata = json.loads(json_match.group())
                self.log_message.emit(f"    [Parser] JSON parsed successfully: title={metadata.get('title', '')[:30] if metadata.get('title') else 'None'}..., keywords_count={len(metadata.get('keywords', '').split(',')) if metadata.get('keywords') else 0}")
                return metadata
            except json.JSONDecodeError as e:
                self.log_message.emit(f"    [Parser] Error parsing JSON (greedy search): {str(e)}")
        
        # If nothing helped
        self.log_message.emit(f"    ❌ Failed to find or parse JSON in response")
        self.log_message.emit(f"    [Parser] First 500 characters of response: {content[:500]}")
        return None
    
    def normalize_words(self, text):
        """Normalizes text and extracts word list (lowercase, without special characters)"""
        if not text:
            return []
        # Extract words: only letters and numbers
        words = re.findall(r'[a-z0-9]+', text.lower())
        return words
    
    def truncate_description(self, description, max_length=80):
        """Truncates description to max_length characters, ending at word boundary (without ellipsis)"""
        if len(description) <= max_length:
            return description
        
        # Truncate to max_length and find last space
        truncated = description[:max_length]
        last_space = truncated.rfind(' ')
        
        # If space found, truncate at it, otherwise truncate hard
        if last_space > 15:  # Minimum 15 characters must remain
            return truncated[:last_space]
        else:
            # If space too close to start, truncate hard
            return truncated
    
    def build_description(self, description_raw, title_words_set):
        """Keeps AI sentence, removes title words and generic words. Returns None if result is unusable"""
        words = [w for w in description_raw.split()
                 if w.lower() not in title_words_set and w.lower() not in DESCRIPTION_BANNED_WORDS]
        description = self.truncate_description(' '.join(words), max_length=80)
        words = description.split()
        # Do not end with a dangling article/preposition
        while words and words[-1].lower() in DESCRIPTION_TRAILING_WORDS:
            words.pop()
        # Do not start with a dangling article/preposition left after removing title words
        while words and words[0].lower() in DESCRIPTION_TRAILING_WORDS - {"a", "an", "the"}:
            words.pop(0)
        if len(words) < 6:
            return None
        description = ' '.join(words)
        description = description[0].upper() + description[1:]
        if len(description) < 15:
            return None
        return description
    
    def have_common_words(self, text1, text2):
        """Checks for common words between two texts"""
        words1 = set(self.normalize_words(text1))
        words2 = set(self.normalize_words(text2))
        return bool(words1 & words2)
    
    def analyze_and_generate_metadata(self, image_path, video_info=None):
        """Analyzes image (or video) file and generates metadata based on content analysis"""
        self.log_message.emit(f"    [Metadata] Starting metadata generation for {'video' if video_info else 'image'}...")
        
        # Adobe Stock: vertical clips must have "vertical" and "video" in title and keywords
        required_words = []
        if video_info and get_orientation(video_info['width'], video_info['height']) == 'vertical':
            required_words = ['vertical', 'video']
        category = 'Video' if video_info else 'Photography'
        
        # Пытаемся проаналfromировать через AI
        ai_metadata = self.analyze_image_with_ai(image_path, video_info)
        
        if ai_metadata:
            self.log_message.emit(f"    [Metadata] AI metadata received, starting processing...")
            title_raw = self.clean_text(ai_metadata.get('title', ''))
            description_raw = self.clean_text(ai_metadata.get('description', ''))
            keywords_str_raw = ai_metadata.get('keywords', '')
            
            self.log_message.emit(f"    [Metadata] Received from AI: title='{title_raw[:30]}...', description='{description_raw[:30]}...', keywords_count={len(keywords_str_raw.split(',')) if keywords_str_raw else 0}")
            
            # All content words from AI analysis (reserve source for title/keywords)
            all_text = f"{title_raw} {description_raw} {keywords_str_raw}".lower()
            all_words_filtered = list(dict.fromkeys(
                w for w in self.normalize_words(all_text) if len(w) >= 3 and w not in STOP_WORDS))
            
            # STEP 1: TITLE (6-10 unique words, no stop words)
            title_words = list(dict.fromkeys(
                w for w in self.normalize_words(title_raw) if len(w) >= 3 and w not in STOP_WORDS))
            if len(title_words) <= 5:
                # Supplement from AI keywords, avoiding description words (otherwise description loses them)
                desc_raw_words = set(self.normalize_words(description_raw))
                ai_keywords = [w for kw in keywords_str_raw.split(',') for w in self.normalize_words(kw)[:1]]
                for word in ai_keywords + all_words_filtered:
                    if len(title_words) >= 6:
                        break
                    if (word not in title_words and word not in desc_raw_words and
                            len(word) >= 3 and word not in STOP_WORDS):
                        title_words.append(word)
            if required_words:
                title_words = [w for w in title_words if w not in required_words]
                title_words = title_words[:10 - len(required_words)] + required_words
            title_words = title_words[:10]
            title = ' '.join(w.title() for w in title_words)
            title_words_set = set(title_words)
            if len(title_words) <= 5:
                self.log_message.emit(f"    ⚠ WARNING: Title contains only {len(title_words)} words (requires more than 5)")
            self.log_message.emit(f"    [Metadata] TITLE: '{title}' ({len(title_words)} words)")
            
            # STEP 2: DESCRIPTION - AI sentence without title words and generic words
            forbidden = sorted(set(w.lower() for w in description_raw.split())
                               & (title_words_set | DESCRIPTION_BANNED_WORDS))
            too_long = len(description_raw) > 80
            if forbidden or too_long:
                # Ask the model to rewrite the sentence instead of cutting words out of it or truncating it
                reasons = []
                if forbidden:
                    reasons.append(f"uses title/generic words {forbidden}")
                if too_long:
                    reasons.append(f"is {len(description_raw)} characters (max 80)")
                self.log_message.emit(f"    [Metadata] Description {' and '.join(reasons)}, asking AI to rewrite...")
                rewritten = self._rewrite_description(description_raw, sorted(title_words_set | DESCRIPTION_BANNED_WORDS))
                if rewritten:
                    self.log_message.emit(f"    [Metadata] Rewritten description: '{rewritten}'")
                    description_raw = rewritten
            description = self.build_description(description_raw, title_words_set)
            if description is None:
                # Fallback: word list from AI analysis, without title words
                self.log_message.emit(f"    ⚠ WARNING: AI description unusable after removing title words, building from analysis words")
                fallback_words = [w for w in all_words_filtered if w not in title_words_set][:12]
                description = self.truncate_description(' '.join(fallback_words).capitalize(), max_length=80)
            desc_words_set = set(self.normalize_words(description))
            self.log_message.emit(f"    [Metadata] DESCRIPTION: '{description}' ({len(description)} characters)")
            
            # STEP 3: KEYWORDS - real words from AI only: not in title, not in description,
            # no singular/plural duplicates, up to MAX_KEYWORDS
            keywords_list = list(required_words)
            keywords_seen = set(keywords_list)
            
            def add_keyword(word):
                if (len(word) < 3 or word in STOP_WORDS or word in keywords_seen or
                        word in title_words_set or word in desc_words_set):
                    return
                # Skip singular/plural duplicate of an existing keyword
                if (word + 's' in keywords_seen or word + 'es' in keywords_seen or
                        (word.endswith('s') and word[:-1] in keywords_seen) or
                        (word.endswith('es') and word[:-2] in keywords_seen)):
                    return
                keywords_list.append(word)
                keywords_seen.add(word)
            
            for kw in keywords_str_raw.split(','):
                words = self.normalize_words(kw)
                if len(words) == 1:
                    add_keyword(words[0])
            from_ai = len(keywords_list)
            # Supplement from other AI words (title/description words are excluded by rules)
            for word in all_words_filtered:
                add_keyword(word)
            keywords_list = keywords_list[:MAX_KEYWORDS]
            
            self.log_message.emit(f"    [Metadata] KEYWORDS: {len(keywords_list)} (from AI keywords: {from_ai})")
            if len(keywords_list) < MIN_KEYWORDS:
                self.log_message.emit(f"    ⚠ WARNING: Only {len(keywords_list)} keywords (recommended {MIN_KEYWORDS}-{MAX_KEYWORDS})")
            keywords = ', '.join(keywords_list)
            
            # STEP 4: Final validation
            common_title_desc = title_words_set & desc_words_set
            if common_title_desc:
                raise Exception(f"❌ CRITICAL ERROR: Title and Description contain common words: {common_title_desc}")
            common_desc_kw = desc_words_set & set(keywords_list)
            if common_desc_kw:
                raise Exception(f"❌ CRITICAL ERROR: Description and Keywords contain common words: {common_desc_kw}")
            if len(description) < 15 or len(description) > 80:
                raise Exception(f"❌ CRITICAL ERROR: Description contains {len(description)} characters (requires 15-80)")
            
            self.log_message.emit(f"    ✓ AI analysis completed: title={len(title_words)} words, description={len(description)} characters, keywords={len(keywords_list)} words")
            
            return {
                'title': title,
                'description': description,
                'keywords': keywords,
                'category': category,
                'model_release': 'No'
            }
        
        # Fallback: use basic generation based on filename
        self.log_message.emit(f"    [Metadata] Use basic generation based on filename")
        stem = image_path.stem
        cleaned_stem = self.clean_text(stem)
        
        title = cleaned_stem.replace('_', ' ').replace('-', ' ').title()
        title = ' '.join(title.split())
        
        keywords = self.extract_words(cleaned_stem, max_words=MAX_KEYWORDS)
        
        keyword_set = set(keywords.lower().replace(', ', ',').split(','))
        description_words = [w for w in cleaned_stem.lower().split() if w not in keyword_set]
        
        if not description_words:
            # Используем wordsа from title
            title_words = cleaned_stem.split()
            if title_words and len(title_words) >= 6:
                description = ' '.join(title_words[:10]).capitalize()
            elif title_words:
                # Дополняем до 6 words, повторяя wordsа from title
                extended_words = title_words * 2  # Дублируем для получения больше words
                description = ' '.join(extended_words[:10]).capitalize()
            else:
                # Критическая ошибка - нет данных для description
                error_msg = "❌ CRITICAL ERROR: Не удалось сформировать description from имени файла"
                self.log_message.emit(f"    {error_msg}")
                raise Exception(error_msg)
        else:
            description = ' '.join(description_words[:10])
            description = description.capitalize()
            
        # Limit to 80 characters, truncating at word boundarysа (without ellipsis)
        description = self.truncate_description(description, max_length=80)
        
        return {
            'title': title,
            'description': description,
            'keywords': keywords,
            'category': category,
            'model_release': 'No'
        }
    
    def write_metadata_to_image(self, image_path, metadata):
        """Writes metadata (title, description, keywords) в файл fromображения"""
        self.log_message.emit(f"    [Write] Starting metadata write to file...")
        
        try:
            # Подготовка метаданных для EXIF/IPTC
            title = metadata.get('title', '')
            description = metadata.get('description', '')
            keywords_str = metadata.get('keywords', '')
            
            self.log_message.emit(f"    [Write] Metadata: title='{title[:30]}...', description='{description[:30]}...', keywords_count={len(keywords_str.split(',')) if keywords_str else 0}")
            
            # Split keywords into list
            keywords_list = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
            
            # For JPEG use piexif to write EXIF/IPTC
            if image_path.suffix.lower() in ['.jpg', '.jpeg']:
                self.log_message.emit(f"    [Write] JPEG format, use piexif to write EXIF/IPTC...")
                
                # Load existing EXIF or create new
                try:
                    exif_dict = piexif.load(str(image_path))
                    self.log_message.emit(f"    [Write] Existing EXIF loaded")
                except:
                    exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
                    self.log_message.emit(f"    [Write] Создан новый EXIF wordsарь")
                
                # Write Title to ImageDescription (EXIF) - read by most programs
                if title:
                    exif_dict["0th"][piexif.ImageIFD.ImageDescription] = title.encode('utf-8')
                    # Windows XP Title (read by Windows and many programs)
                    try:
                        exif_dict["0th"][piexif.ImageIFD.XPTitle] = title.encode('utf-16le') + b'\x00\x00'
                    except:
                        pass
                    self.log_message.emit(f"    [Write] Title written to EXIF")
                
                # Write Description to UserComment (EXIF)
                if description:
                    # UserComment in format: encoding + text (read by many programs)
                    user_comment = b'unicode\x00\x00' + description.encode('utf-16le') + b'\x00\x00'
                    exif_dict["Exif"][piexif.ExifIFD.UserComment] = user_comment
                    # Windows XP Comment
                    try:
                        exif_dict["0th"][piexif.ImageIFD.XPComment] = description.encode('utf-16le') + b'\x00\x00'
                    except:
                        pass
                    self.log_message.emit(f"    [Write] Description written to EXIF")
                
                # Write Keywords (EXIF)
                if keywords_list:
                    # Windows XP Keywords (read by many programs)
                    try:
                        keywords_utf16 = b'\x00\x00'.join([kw.encode('utf-16le') for kw in keywords_list]) + b'\x00\x00'
                        exif_dict["0th"][piexif.ImageIFD.XPKeywords] = keywords_utf16
                        self.log_message.emit(f"    [Write] Keywords written to EXIF ({len(keywords_list)} words)")
                    except:
                        pass
                
                # Открываем fromображение для сохранения
                img = Image.open(image_path)
                
                # Save EXIF metadata
                exif_bytes = piexif.dump(exif_dict)
                img.save(str(image_path), "JPEG", exif=exif_bytes, quality=95, optimize=False)
                img.close()
                
                self.log_message.emit(f"    [Write] EXIF metadata saved to file")
                
                # Try to write IPTC metadata through exiftool (if available)
                # This is needed for macOS Photos and other programs, which read IPTC
                try:
                    self.write_iptc_with_exiftool(image_path, title, description, keywords_list)
                    self.log_message.emit(f"    [Write] IPTC metadata written through exiftool")
                except FileNotFoundError:
                    # If exiftool unavailable, continue with EXIF data
                    self.log_message.emit(f"    [Write] Note: exiftool not found. Install: brew install exiftool")
                    self.log_message.emit(f"    [Write] Use only EXIF metadata (some programs may not see)")
                except Exception as e:
                    # Другие ошибки игнорируем
                    self.log_message.emit(f"    [Write] Error writing IPTC through exiftool: {str(e)}")
                
                # Log what was written
                self.log_message.emit(f"    [Write] Written: Title='{title[:30]}...', Description='{description[:30]}...', Keywords={len(keywords_list)} words")
                self.log_message.emit(f"    [Write] Check file through: python check_metadata.py '{image_path}'")
                
            else:
                # For other formats use Pillow info
                self.log_message.emit(f"    [Write] Format {image_path.suffix}, use Pillow info...")
                img = Image.open(image_path)
                info = img.info.copy()
                
                if title:
                    info['title'] = title
                if description:
                    info['description'] = description
                if keywords_list:
                    info['keywords'] = keywords_list
                
                img.save(str(image_path), **info)
                img.close()
                self.log_message.emit(f"    [Write] Metadata сохранены через Pillow info")
            
        except Exception as e:
            raise Exception(f"Error writing metadata: {str(e)}")
    
    def write_video_csv_row(self, filename, metadata):
        """Appends video metadata to Adobe Stock CSV (Filename, Title, Keywords, Category, Releases)"""
        csv_path = Path(self.output_folder) / VIDEO_CSV_NAME
        mode = 'a' if self._video_csv_started else 'w'
        with open(csv_path, mode, newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not self._video_csv_started:
                writer.writerow(['Filename', 'Title', 'Keywords', 'Category', 'Releases'])
            writer.writerow([filename, metadata.get('title', ''), metadata.get('keywords', ''), '', ''])
        self._video_csv_started = True
        self.log_message.emit(f"    [Write] Video metadata added to {VIDEO_CSV_NAME} (video file is not copied)")
    
    def write_iptc_with_exiftool(self, image_path, title, description, keywords_list):
        """Writes IPTC metadata through exiftool (for compatibility with macOS Photos)"""
        self.log_message.emit(f"    [Write IPTC] Starting IPTC metadata write through exiftool...")
        
        try:
            # Check for exiftool
            result = subprocess.run(['which', 'exiftool'], capture_output=True, text=True)
            if result.returncode != 0:
                raise FileNotFoundError("exiftool not found")
            
            self.log_message.emit(f"    [Write IPTC] exiftool found")
            
            # Form exiftool command
            cmd = ['exiftool', '-overwrite_original', '-q']
            
            # Title (IPTC ObjectName)
            if title:
                cmd.extend(['-IPTC:ObjectName=' + title])
                cmd.extend(['-XMP:Title=' + title])
                self.log_message.emit(f"    [Write IPTC] Title added to command")
            
            # Description (IPTC Caption-Abstract)
            if description:
                cmd.extend(['-IPTC:Caption-Abstract=' + description])
                cmd.extend(['-XMP:Description=' + description])
                self.log_message.emit(f"    [Write IPTC] Description added to command")
            
            # Keywords (IPTC Keywords)
            if keywords_list:
                for keyword in keywords_list:
                    cmd.extend(['-IPTC:Keywords+=' + keyword])
                cmd.extend(['-XMP:Subject=' + ','.join(keywords_list)])
                self.log_message.emit(f"    [Write IPTC] Keywords added to command ({len(keywords_list)} words)")
            
            # Add file path
            cmd.append(str(image_path))
            
            self.log_message.emit(f"    [Write IPTC] Executing exiftool command...")
            
            # Execute command
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                self.log_message.emit(f"    [Write IPTC] IPTC metadata successfully written")
            else:
                self.log_message.emit(f"    [Write IPTC] Warning: exiftool returned code {result.returncode}")
                if result.stderr:
                    self.log_message.emit(f"    [Write IPTC] exiftool error: {result.stderr[:200]}")
                    
        except FileNotFoundError:
            raise
        except subprocess.TimeoutExpired:
            self.log_message.emit(f"    [Write IPTC] Error: exiftool execution timeout")
            raise Exception("exiftool execution timeout")
        except Exception as e:
            self.log_message.emit(f"    [Write IPTC] Error writing IPTC: {str(e)}")
            raise


class EditDialog(QDialog):
    def __init__(self, column_name, current_value, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit {column_name}")
        self.setModal(True)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"{column_name}:"))
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(current_value)
        layout.addWidget(self.text_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def get_value(self):
        return self.text_edit.text()


class KeyCutterApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"TagStock PhotoKey {__version__} - Batch image processing for stock")
        self.setGeometry(100, 100, 1200, 800)
        
        # Set window icon
        self.set_window_icon()
        
        # Data for processing
        self.selected_folder = None
        self.output_folder = None
        self.processing_thread = None
        self._processing_stopped = False  # Flag for stopping processing
        
        self.create_ui()
    
    def set_window_icon(self):
        """Sets window icon from logo"""
        logo_path = self.get_logo_path()
        if logo_path and os.path.exists(logo_path):
            try:
                icon = QIcon(logo_path)
                self.setWindowIcon(icon)
            except Exception as e:
                print(f"Failed to load icon: {e}")
    
    def get_logo_path(self):
        """Returns path to logo"""
        # Try to find logo in different places
        possible_paths = [
            os.path.join(os.path.dirname(__file__), 'assets', 'logo.png'),
            os.path.join(os.path.dirname(__file__), 'assets', 'logo.jpg'),
            os.path.join(os.path.dirname(__file__), 'logo.png'),
            os.path.join(os.path.dirname(__file__), 'logo.jpg'),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return None
    
    def create_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout()
        central_widget.setLayout(layout)
        
        # Create main interface
        self.create_main_interface(layout)
    
    def create_main_interface(self, layout):
        
        # Logo at top of interface
        logo_path = self.get_logo_path()
        if logo_path and os.path.exists(logo_path):
            try:
                logo_label = QLabel()
                pixmap = QPixmap(logo_path)
                # Scale logo to reasonable size (maximum width 300px)
                if pixmap.width() > 300:
                    pixmap = pixmap.scaledToWidth(300, Qt.TransformationMode.SmoothTransformation)
                logo_label.setPixmap(pixmap)
                logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(logo_label)
            except Exception as e:
                print(f"Failed to load logo: {e}")
        
        # Select folder with JPEG images
        folder_group = QGroupBox("Folder with source JPEG and video files (MOV, MP4, MPG)")
        folder_layout = QHBoxLayout()
        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setReadOnly(True)
        folder_btn = QPushButton("Select folder")
        folder_btn.clicked.connect(self.select_input_folder)
        folder_layout.addWidget(self.folder_path_edit)
        folder_layout.addWidget(folder_btn)
        folder_group.setLayout(folder_layout)
        layout.addWidget(folder_group)
        
        # Select folder for saving processed files
        output_group = QGroupBox("Folder for saving processed files")
        output_layout = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setReadOnly(True)
        output_btn = QPushButton("Select folder")
        output_btn.clicked.connect(self.select_output_folder)
        output_layout.addWidget(self.output_path_edit)
        output_layout.addWidget(output_btn)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        # Processing settings
        settings_group = QGroupBox("Settings")
        settings_layout = QVBoxLayout()
        
        # API key (automatically set, can be changed)
        api_key_layout = QHBoxLayout()
        api_key_label = QLabel("API Key (GPT):")
        self.api_key_edit = QLineEdit()
        # Last used key from keychain, otherwise OPENAI_API_KEY environment variable
        self.api_key_edit.setText(load_saved_api_key() or os.getenv('OPENAI_API_KEY', ''))
        self.api_key_edit.setPlaceholderText("sk-... (OpenAI GPT API key)")
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_layout.addWidget(api_key_label)
        api_key_layout.addWidget(self.api_key_edit)
        settings_layout.addLayout(api_key_layout)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # Processing control buttons
        buttons_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start processing")
        self.start_btn.clicked.connect(self.start_processing)
        buttons_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_processing)
        self.stop_btn.setEnabled(False)  # Inactive by default
        buttons_layout.addWidget(self.stop_btn)
        
        layout.addLayout(buttons_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        layout.addWidget(self.progress_bar)
        
        # Processing log
        log_group = QGroupBox("Processing log")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
    
    def select_input_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder with JPEG and video files")
        if folder:
            self.folder_path_edit.setText(folder)
            self.selected_folder = folder
    
    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder for saving processed files")
        if folder:
            self.output_path_edit.setText(folder)
            self.output_folder = folder
    
    def log(self, message):
        """Adds message to log"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.append(f"{timestamp} - {message}")
    
    def start_processing(self):
        if not self.selected_folder or not self.output_folder:
            QMessageBox.critical(self, "Error", "Select input and output folders")
            return
        
        if self.processing_thread and self.processing_thread.isRunning():
            QMessageBox.warning(self, "Warning", "Processing already in progress")
            return
        
        # Clear log
        self.log_text.clear()
        
        # Manage buttons
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)  # Activate stop button
        self.progress_bar.setValue(0)
        
        # Create and start thread
        api_key = self.api_key_edit.text().strip() if hasattr(self, 'api_key_edit') and self.api_key_edit.text().strip() else None
        
        # Remember the key for next launch
        if api_key and api_key != load_saved_api_key():
            if save_api_key(api_key):
                self.log("[UI] API key saved to keychain, it will be used on next launch")
            else:
                self.log("[UI] ⚠ Failed to save API key to keychain")
        
        self.log(f"[UI] Creating processing thread: api_type=openai (GPT), generate_metadata=True")
        
        # Metadata generation always enabled by default
        self.processing_thread = ProcessingThread(
            self.selected_folder,
            self.output_folder,
            generate_metadata=True,  # Always enabled
            api_key=api_key  # Using automatic key, if no other specified
        )
        self.processing_thread.progress.connect(self.update_progress)
        self.processing_thread.log_message.connect(self.log)
        self.processing_thread.finished.connect(self.processing_finished)
        self._processing_stopped = False  # Reset stop flag
        self.processing_thread.start()
    
    def update_progress(self, current, total):
        """Updates progress bar"""
        value = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(value)
    
    def stop_processing(self):
        """Stops processing"""
        if self.processing_thread and self.processing_thread.isRunning():
            self._processing_stopped = True
            self.processing_thread.stop()
            self.log("Processing stop requested...")
            # Buttons will be updated in processing_finished
    
    def clean_text(self, text):
        """Cleans text from special characters, keeps only English letters, numbers and spaces"""
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', text)
        cleaned = ' '.join(cleaned.split())
        return cleaned
    
    def extract_words(self, text, max_words=50):
        """Extracts individual words from text (not phrases)"""
        cleaned = self.clean_text(text)
        words = cleaned.lower().split()
        unique_words = []
        seen = set()
        for word in words:
            if word not in seen and len(word) > 0:
                unique_words.append(word)
                seen.add(word)
                if len(unique_words) >= max_words:
                    break
        return ', '.join(unique_words)
    
    def processing_finished(self, data):
        """Called after processing completion"""
        self.log("[UI] Processing completed, updating interface...")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)  # Deactivate stop button
        self.progress_bar.setValue(100)
        
        # Show message only if processing was not stopped
        if not self._processing_stopped:
            self.log("[UI] Showing success completion message")
            QMessageBox.information(
                self,
                "Done",
                f"Processing completed!\nPhotos with metadata and {VIDEO_CSV_NAME} (for videos) saved to output folder.\nSee the log for videos that do not meet Adobe Stock requirements."
            )
        else:
            self._processing_stopped = False  # Reset flag
            self.log("[UI] Processing was stopped by user")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = KeyCutterApp()
    window.show()
    sys.exit(app.exec())
