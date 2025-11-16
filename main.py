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
from datetime import datetime
from PIL import Image
import piexif
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Local models removed - using only OpenAI API


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
        # Automatic GPT API key (if no other key is provided)
        self.api_key = api_key or "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"
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
        
        # Find only JPEG files
        image_extensions = ['.jpg', '.jpeg']
        image_files = []
        
        self.log_message.emit(f"[Processing] Searching for JPEG files in folder: {self.input_folder}")
        for ext in image_extensions:
            found_lower = list(Path(self.input_folder).glob(f"*{ext}"))
            found_upper = list(Path(self.input_folder).glob(f"*{ext.upper()}"))
            image_files.extend(found_lower)
            image_files.extend(found_upper)
            self.log_message.emit(f"[Processing] Found files with extension {ext}: {len(found_lower)} (lowercase), {len(found_upper)} (uppercase)")
        
        total = len(image_files)
        self.log_message.emit(f"[Processing] Total JPEG files found: {total}")
        
        if total == 0:
            self.log_message.emit("[Processing] ERROR: JPEG files not found!")
            self.finished.emit([])
            return
        
        # Create output folder if it doesn't exist
        self.log_message.emit(f"[Processing] Creating output folder (if not exists): {self.output_folder}")
        Path(self.output_folder).mkdir(parents=True, exist_ok=True)
        self.log_message.emit(f"[Processing] Output folder ready")
        
        processed_count = 0
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
                        metadata = self.analyze_and_generate_metadata(output_file_path)
                        self.log_message.emit(f"[Processing] Metadata successfully generated for file {idx}/{total}")
                    except Exception as e:
                        # If API error, stop processing
                        error_msg = str(e)
                        self.log_message.emit(f"    ❌ [Processing] CRITICAL ERROR: {error_msg}")
                        import traceback
                        self.log_message.emit(f"    [Processing] Error details: {traceback.format_exc()}")
                        self.log_message.emit("[Processing] Processing stopped due to API error")
                        self.log_message.emit(f"[Processing] Processed files: {processed_count} of {total}")
                        self.finished.emit([])
                        return
                    
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
            self.log_message.emit("=" * 80)
        else:
            self.log_message.emit("[Processing] Processing was stopped by user")
        
        self.finished.emit([])
    
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
    
    def analyze_image_with_ai(self, image_path):
        """Analyzes image content through OpenAI GPT API"""
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
        result = self._analyze_with_openai_api(image_path, api_key)
        # If OpenAI API failed (error, quota, etc.), stop processing
        if result is None:
            error_msg = "ERROR: OpenAI API is not working (check quota and API key). Processing stopped."
            self.log_message.emit(f"    ❌ {error_msg}")
            raise Exception(error_msg)
        self.log_message.emit(f"    [AI] OpenAI GPT API returned result: title={result.get('title', '')[:30] if result else 'None'}...")
        return result
    
    def _analyze_with_openai_api(self, image_path, api_key):
        """Analysis through OpenAI API"""
        self.log_message.emit(f"    [OpenAI] Starting analysis through OpenAI API...")
        
        if not OPENAI_AVAILABLE:
            error_msg = "ERROR: OpenAI not installed. Install: pip install openai"
            self.log_message.emit(f"    ❌ {error_msg}")
            raise Exception(error_msg)
        
        try:
            self.log_message.emit(f"    [OpenAI] Opening and encoding image...")
            # Open and encode image
            with open(image_path, 'rb') as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')
            
            self.log_message.emit(f"    [OpenAI] Image encoded, size: {len(image_data)} characters")
            
            # Use standard OpenAI endpoint
            self.log_message.emit(f"    [OpenAI] Using standard OpenAI endpoint")
            client = OpenAI(api_key=api_key)
            
            self.log_message.emit(f"    [OpenAI] Sending request to API (model: gpt-5.1)...")
            
            # Request to API for image analysis
            response = client.chat.completions.create(
                model="gpt-5.1",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """Analyze this image carefully and describe what you see. Then provide metadata for stock photography.

IMPORTANT: Look at the image and describe what is actually shown - the main subject, objects, animals, people, scenery, colors, actions, etc.

Return ONLY a JSON object with this exact structure (no markdown, no code blocks):
{
  "title": "descriptive title based on what you see in the image, English only, no special characters",
  "description": "detailed description of what is in the image, English only, no special characters, maximum 80 characters, describe the scene/subject but do NOT include keywords",
  "keywords": "comma-separated list of EXACTLY 50 individual words describing the image content, English only, no special characters, only single words not phrases. YOU MUST PROVIDE EXACTLY 50 WORDS - describe the main subject, objects, colors, textures, actions, environment, background, foreground, details, mood, season, time of day, weather, and any other relevant aspects. NO MORE, NO LESS."
}

CRITICAL RULES:
- Title: Describe the main subject/scene with MORE THAN 5 WORDS (e.g. "Deer Grazing On Green Grass In Field", "Sunset Over Mountains With Clouds"). Only English letters and spaces, no special characters. YOU MUST PROVIDE MORE THAN 5 WORDS.
- Description: Describe what you see in detail but without using keyword words with MORE THAN 5 WORDS (e.g. "Wildlife photography showing animal in natural habitat with fence and trees in background"). Maximum 80 characters, English only, no special characters. YOU MUST PROVIDE MORE THAN 5 WORDS.
- Keywords: List EXACTLY 50 individual words separated by commas (e.g. "deer, wildlife, nature, grass, animal, mammal, forest, outdoor, wild, grazing, brown, green, fence, trees, sky, sunny, natural, habitat"). YOU MUST PROVIDE EXACTLY 50 WORDS - describe the main subject, objects, colors, textures, actions, environment, background, foreground, details, mood, season, time of day, weather, and any other relevant aspects. Only single words, no phrases, English only, no special characters. This is CRITICAL - you must provide exactly 50 words.

Analyze the image NOW and return ONLY the JSON object with EXACTLY 50 keywords."""
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                max_completion_tokens=1500,  # Increased to guarantee complete JSON with 50 keywords (enough for 100+ photos)
                temperature=0.3
            )
            
            self.log_message.emit(f"    [OpenAI] Response received from API")
            
            # Parse response
            content = response.choices[0].message.content.strip()
            self.log_message.emit(f"    [OpenAI] AI response received, length: {len(content)} characters")
            
            return self._parse_ai_response(content)
                
        except Exception as e:
            error_str = str(e)
            # Handle rate limit errors
            if "rate limit" in error_str.lower() or "429" in error_str:
                self.log_message.emit(f"    ⚠ Rate limit reached, waiting 60 seconds...")
                time.sleep(60)  # Wait 60 seconds on rate limit
                # Try to retry request once
                try:
                    self.log_message.emit(f"    [OpenAI] Retrying after rate limit...")
                    response = client.chat.completions.create(
                        model="gpt-5.1",
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": """Analyze this image carefully and describe what you see. Then provide metadata for stock photography.

IMPORTANT: Look at the image and describe what is actually shown - the main subject, objects, animals, people, scenery, colors, actions, etc.

Return ONLY a JSON object with this exact structure (no markdown, no code blocks):
{
  "title": "descriptive title based on what you see in the image, English only, no special characters",
  "description": "detailed description of what is in the image, English only, no special characters, maximum 80 characters, describe the scene/subject but do NOT include keywords",
  "keywords": "comma-separated list of EXACTLY 50 individual words describing the image content, English only, no special characters, only single words not phrases. YOU MUST PROVIDE EXACTLY 50 WORDS - describe the main subject, objects, colors, textures, actions, environment, background, foreground, details, mood, season, time of day, weather, and any other relevant aspects. NO MORE, NO LESS."
}

CRITICAL RULES:
- Title: Describe the main subject/scene with MORE THAN 5 WORDS (e.g. "Deer Grazing On Green Grass In Field", "Sunset Over Mountains With Clouds"). Only English letters and spaces, no special characters. YOU MUST PROVIDE MORE THAN 5 WORDS.
- Description: Describe what you see in detail but without using keyword words with MORE THAN 5 WORDS (e.g. "Wildlife photography showing animal in natural habitat with fence and trees in background"). Maximum 80 characters, English only, no special characters. YOU MUST PROVIDE MORE THAN 5 WORDS.
- Keywords: List EXACTLY 50 individual words separated by commas (e.g. "deer, wildlife, nature, grass, animal, mammal, forest, outdoor, wild, grazing, brown, green, fence, trees, sky, sunny, natural, habitat"). YOU MUST PROVIDE EXACTLY 50 WORDS - describe the main subject, objects, colors, textures, actions, environment, background, foreground, details, mood, season, time of day, weather, and any other relevant aspects. Only single words, no phrases, English only, no special characters. This is CRITICAL - you must provide exactly 50 words.

Analyze the image NOW and return ONLY the JSON object with EXACTLY 50 keywords."""
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{image_data}"
                                        }
                                    }
                                ]
                            }
                        ],
                        max_completion_tokens=1500,
                        temperature=0.3
                    )
                    content = response.choices[0].message.content.strip()
                    self.log_message.emit(f"    [OpenAI] Response received after retry")
                    return self._parse_ai_response(content)
                except Exception as e2:
                    self.log_message.emit(f"    ❌ Error on retry: {str(e2)}")
            
            self.log_message.emit(f"    ❌ Error analyzing through OpenAI API: {error_str}")
            import traceback
            self.log_message.emit(f"    [OpenAI] Error details: {traceback.format_exc()}")
            return None
    
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
    
    def have_common_words(self, text1, text2):
        """Checks for common words between two texts"""
        words1 = set(self.normalize_words(text1))
        words2 = set(self.normalize_words(text2))
        return bool(words1 & words2)
    
    def analyze_and_generate_metadata(self, image_path):
        """Analyzes image file and generates metadata based on content analysis"""
        self.log_message.emit(f"    [Metadata] Starting metadata generation for image...")
        
        # Пытаемся проаналfromировать через AI
        ai_metadata = self.analyze_image_with_ai(image_path)
        
        if ai_metadata:
            self.log_message.emit(f"    [Metadata] AI metadata received, starting processing...")
            # STEP 1: Collect ALL words from AI analysis
            title_raw = self.clean_text(ai_metadata.get('title', ''))
            description_raw = self.clean_text(ai_metadata.get('description', ''))
            keywords_str_raw = ai_metadata.get('keywords', '')
            
            self.log_message.emit(f"    [Metadata] Received from AI: title='{title_raw[:30]}...', description='{description_raw[:30]}...', keywords_count={len(keywords_str_raw.split(',')) if keywords_str_raw else 0}")
            
            # Extract all words from all sources
            all_text = f"{title_raw} {description_raw} {keywords_str_raw}".lower()
            all_words = self.normalize_words(all_text)
            
            # Stop words for filtering
            stop_words = {
                "the", "a", "an", "of", "in", "on", "at", "to", "for", "with", "is", "are", "was", "were",
                "and", "or", "but", "this", "that", "these", "those", "it", "its", "they", "them", "what", "you",
                "by", "from", "as", "be", "have", "has", "had", "do", "does", "did", "will", "would", "could",
                "should", "may", "might", "must", "can", "up", "out", "so", "if", "no", "not", "only", "just",
                "more", "most", "very", "much", "many", "some", "any", "all", "each", "every", "both", "such",
                "than", "too", "also", "here", "there", "where", "when", "why", "how", "who", "which", "whose", "whom",
                "see", "image", "photography", "photo", "picture", "detailed", "describe", "scene", "happening",
                "showing", "view", "professional", "high", "quality"
            }
            
            # Filter: only words with length >= 3 characters and not stop words
            all_words_filtered = [w for w in all_words if len(w) >= 3 and w not in stop_words]
            all_words_set = set(all_words_filtered)
            
            self.log_message.emit(f"    [Metadata] Extracted {len(all_words_filtered)} unique words from AI analysis")
            
            # STEP 2: Generate TITLE (without stop words, maximum 10 words, more than 5 words)
            title_words_raw = self.normalize_words(title_raw)
            title_words_candidates = [w for w in title_words_raw if len(w) >= 3 and w not in stop_words]
            
            self.log_message.emit(f"    [Metadata] STEP 2: Generate TITLE from {len(title_words_candidates)} words")
            
            # If title from AI is too short (< 5 words), supplement from all_words
            if len(title_words_candidates) <= 5:
                title_words_candidates = list(dict.fromkeys(title_words_candidates))  # Remove duplicates
                for word in all_words_filtered:
                    if len(title_words_candidates) >= 6:  # More than 5 words
                        break
                    if word not in title_words_candidates:
                        title_words_candidates.append(word)
            
            # Limit to 10 words and format Title Case
            title_words_final = title_words_candidates[:10]
            title = ' '.join([w.title() for w in title_words_final])
            
            # If title still <= 5 words, this is a problem, but continue
            if len(title_words_final) <= 5:
                self.log_message.emit(f"    ⚠ WARNING: Title contains only {len(title_words_final)} words (requires more than 5)")
            
            title_words_set = set([w.lower() for w in title_words_final])
            
            self.log_message.emit(f"    [Metadata] TITLE generated: '{title}' ({len(title_words_final)} words)")
            
            # STEP 3: Generate KEYWORDS (without words from title, up to 50 words)
            keywords_list = []
            keywords_seen = set()
            
            self.log_message.emit(f"    [Metadata] STEP 3: Generate KEYWORDS...")
            
            # First use keywords from AI (if available)
            if keywords_str_raw:
                keywords_raw_list = [self.clean_text(kw.strip()).lower() for kw in keywords_str_raw.split(',') if kw.strip()]
                for kw in keywords_raw_list:
                    kw_clean = self.normalize_words(kw)
                    if kw_clean and len(kw_clean[0]) >= 3:
                        kw_word = kw_clean[0]
                        if (kw_word not in stop_words and 
                            kw_word not in title_words_set and
                            kw_word not in keywords_seen):
                            keywords_list.append(kw_word)
                            keywords_seen.add(kw_word)
                            if len(keywords_list) >= 50:
                                break
            
            self.log_message.emit(f"    [Metadata] From AI keywords received {len(keywords_list)} words")
            
            # Supplement keywords from all_words (but NOT from title)
            if len(keywords_list) < 50:
                for word in all_words_filtered:
                    if len(keywords_list) >= 50:
                        break
                    if (word not in title_words_set and
                        word not in keywords_seen):
                        keywords_list.append(word)
                        keywords_seen.add(word)
            
            self.log_message.emit(f"    [Metadata] After supplementing from all_words: {len(keywords_list)} keywords")
            
            # If still insufficient, generate word variations
            if len(keywords_list) < 50:
                existing_keywords_copy = keywords_list.copy()
                for kw in existing_keywords_copy:
                    if len(keywords_list) >= 50:
                        break
                    
                    # Plural
                    if not kw.endswith('s') and len(kw) >= 3:
                        plural = kw + 's'
                        if (plural not in title_words_set and
                            plural not in keywords_seen and
                            plural not in stop_words):
                            keywords_list.append(plural)
                            keywords_seen.add(plural)
                    
                    # Singular
                    if kw.endswith('s') and len(kw) > 3:
                        singular = kw[:-1]
                        if (singular not in title_words_set and
                            singular not in keywords_seen and
                            len(singular) >= 3 and
                            singular not in stop_words):
                            keywords_list.append(singular)
                            keywords_seen.add(singular)
                    
                    # Remove endings -ing, -ed, -er, -est, -ly
                    for ending, length in [('ing', 3), ('ed', 2), ('er', 2), ('est', 3), ('ly', 2)]:
                        if kw.endswith(ending) and len(kw) > (3 + length):
                            base = kw[:-length]
                            if (base not in title_words_set and
                                base not in keywords_seen and
                                len(base) >= 3 and
                                base not in stop_words):
                                keywords_list.append(base)
                                keywords_seen.add(base)
                                if len(keywords_list) >= 50:
                                    break
                    
                    if len(keywords_list) >= 50:
                        break
            
            self.log_message.emit(f"    [Metadata] After generating variations: {len(keywords_list)} keywords")
            
            # STEP 4: Generate DESCRIPTION (without words from title и keywords, more than 5 words, 15-80 characters)
            # IMPORTANT: description must NOT contain words from title and keywords (0 common words)
            keyword_set_for_desc = set([kw.lower() for kw in keywords_list])
            
            self.log_message.emit(f"    [Metadata] STEP 4: Generate DESCRIPTION...")
            
            description_words_candidates = []
            
            # Strategy 1: Use words from original description from AI, which are NOT in title and NOT in keywords
            if description_raw:
                desc_words_raw = self.normalize_words(description_raw)
                desc_words_filtered = [w for w in desc_words_raw if len(w) >= 3 and w not in stop_words]
                # Take only words, which are not in title and keywords
                for word in desc_words_filtered:
                    if (word not in title_words_set and 
                        word not in keyword_set_for_desc and
                        word not in description_words_candidates):
                        description_words_candidates.append(word)
                        if len(description_words_candidates) >= 15:  # Enough words
                            break
            
            self.log_message.emit(f"    [Metadata] From original description received {len(description_words_candidates)} words")
            
            # Strategy 2: Supplement from all_words with words, which are not in title and keywords
            if len(description_words_candidates) < 6:
                desc_words_seen = set([w.lower() for w in description_words_candidates])
                # Take words from all_words, which are NOT in title, NOT in keywords and NOT already in description
                allowed_words = [w for w in all_words_filtered 
                               if w not in title_words_set and 
                               w not in keyword_set_for_desc and
                               w not in desc_words_seen]
                
                for word in allowed_words:
                    if len(description_words_candidates) >= 15:  # Enough words
                        break
                    description_words_candidates.append(word)
                    desc_words_seen.add(word)
            
            self.log_message.emit(f"    [Metadata] After supplementing from all_words: {len(description_words_candidates)} words для description")
            
            # Strategy 3: If still insufficient, используем wordsа from оригинального AI аналfromа (captions)
            # но fromбегаем words from title и keywords
            if len(description_words_candidates) < 6:
                # Пробуем получить больше words from all_words (maybe they are in original AI response)
                # But do not use words from title and keywords
                desc_words_seen = set([w.lower() for w in description_words_candidates])
                
                # Go through all_words_filtered again, but more aggressively
                for word in all_words_filtered:
                    if len(description_words_candidates) >= 15:
                        break
                    if (word not in title_words_set and
                        word not in keyword_set_for_desc and
                        word not in desc_words_seen):
                        description_words_candidates.append(word)
                        desc_words_seen.add(word)
            
            self.log_message.emit(f"    [Metadata] After aggressive supplementing: {len(description_words_candidates)} words для description")
            
            # Form description
            description = None
            
            if description_words_candidates and len(description_words_candidates) >= 6:
                # Берем максимум 12 words для более лаконичного description
                description = ' '.join(description_words_candidates[:12]).capitalize()
                # Limit to 80 characters, truncating at word boundarysа
                description = self.truncate_description(description, max_length=80)
                self.log_message.emit(f"    ✓ Description сформирован from уникальных words: {description} ({len(self.normalize_words(description))} words)")
            
            # Если не удалось сформировать from уникальных words, try more aggressively
            if not description or len(self.normalize_words(description)) < 6:
                self.log_message.emit(f"    ⚠ WARNING: Не удалось сформировать description from уникальных words, пытаемся использовать дополнительные стратегии")
                
                # Strategy 4: Use words from all_words, which are NOT in title (but may be in keywords)
                # This is better than intersection with title
                desc_words_seen = set()
                description_words_candidates = []
                
                for word in all_words_filtered:
                    if len(description_words_candidates) >= 15:
                        break
                    # EXCLUDE only words from title (this is critical!)
                    if word not in title_words_set and word not in desc_words_seen:
                        description_words_candidates.append(word)
                        desc_words_seen.add(word)
                
                if len(description_words_candidates) >= 6:
                    # Берем максимум 12 words для более лаконичного description
                    description = ' '.join(description_words_candidates[:12]).capitalize()
                    # Limit to 80 characters, truncating at word boundarysа
                    description = self.truncate_description(description, max_length=80)
                    self.log_message.emit(f"    ⚠ WARNING: Description сформирован from all_words (fromбегая title): {description} ({len(self.normalize_words(description))} words)")
                else:
                    # Strategy 5: If still insufficient, use words from keywords_str_raw, which are not in title
                    if keywords_str_raw:
                        keywords_raw_list = [kw.strip() for kw in keywords_str_raw.replace(',', ',').split(',') if kw.strip()]
                        keywords_raw_normalized = []
                        for kw in keywords_raw_list:
                            words = self.normalize_words(kw)
                            keywords_raw_normalized.extend([w for w in words if len(w) >= 3 and w not in stop_words])
                        
                        desc_words_seen = set()
                        description_words_candidates = []
                        
                        for word in keywords_raw_normalized:
                            if len(description_words_candidates) >= 15:
                                break
                            # EXCLUDE only words from title
                            if word not in title_words_set and word not in desc_words_seen:
                                description_words_candidates.append(word)
                                desc_words_seen.add(word)
                        
                        if len(description_words_candidates) >= 6:
                            # Берем максимум 12 words для более лаконичного description
                            description = ' '.join(description_words_candidates[:12]).capitalize()
                            # Limit to 80 characters, truncating at word boundarysа
                            description = self.truncate_description(description, max_length=80)
                            self.log_message.emit(f"    ⚠ WARNING: Description сформирован from keywords_raw (fromбегая title): {description} ({len(self.normalize_words(description))} words)")
                
                # If still failed - critical error
                if not description or len(self.normalize_words(description)) < 6:
                    error_msg = f"❌ CRITICAL ERROR: Не удалось сформировать description from аналfromа fromображения (нет достаточного количества уникальных words, which are not in title)"
                    self.log_message.emit(f"    {error_msg}")
                    self.log_message.emit(f"    [Metadata] Debug information: title_words={len(title_words_set)}, all_words={len(all_words_filtered)}, keywords_count={len(keywords_list)}")
                    raise Exception(error_msg)
            
            # CRITICAL CHECK: Убеждаемся, что description НЕ содержит words from title
            desc_words_final = set(self.normalize_words(description))
            common_with_title = desc_words_final & title_words_set
            
            if common_with_title:
                self.log_message.emit(f"    ❌ CRITICAL ERROR: Description contains wordsа from title: {common_with_title}")
                # Regeneration attempt: remove общие wordsа from description и дополняем уникальными
                desc_words_unique = [w for w in desc_words_final if w not in title_words_set]
                
                # Дополняем до 6+ words уникальными wordsами
                for word in all_words_filtered:
                    if len(desc_words_unique) >= 15:
                        break
                    if word not in title_words_set and word not in desc_words_unique:
                        desc_words_unique.append(word)
                
                if len(desc_words_unique) >= 6:
                    # Берем максимум 12 words для более лаконичного description
                    description = ' '.join(list(desc_words_unique)[:12]).capitalize()
                    # Limit to 80 characters, truncating at word boundarysа
                    description = self.truncate_description(description, max_length=80)
                    self.log_message.emit(f"    ✓ Description перегенерирован without words from title: {description} ({len(self.normalize_words(description))} words)")
                else:
                    error_msg = f"❌ CRITICAL ERROR: Не удалось перегенерировать description without words from title (only available {len(desc_words_unique)} уникальных words)"
                    self.log_message.emit(f"    {error_msg}")
                    raise Exception(error_msg)
            
            # Проверяем, что description содержит more than 5 words
            desc_words_check = self.normalize_words(description)
            if len(desc_words_check) <= 5:
                error_msg = f"❌ CRITICAL ERROR: Description contains only {len(desc_words_check)} words (requires more than 5)"
                self.log_message.emit(f"    {error_msg}")
                raise Exception(error_msg)
            
            # STEP 5: Final filtering of KEYWORDS from DESCRIPTION
            desc_words_set = set(self.normalize_words(description))
            keywords_filtered = [kw for kw in keywords_list if kw.lower() not in desc_words_set]
            
            self.log_message.emit(f"    [Metadata] STEP 5: Filtering keywords from description: was {len(keywords_list)}, became {len(keywords_filtered)}")
            
            # STEP 6: Fill KEYWORDS to 50 (aggressively)
            keywords_filtered_set = set([kw.lower() for kw in keywords_filtered])
            
            self.log_message.emit(f"    [Metadata] STEP 6: Добивка keywords до 50...")
            
            # Strategy 1: Add words from all_words, which are not in title, description и keywords
            if len(keywords_filtered) < 50:
                for word in all_words_filtered:
                    if len(keywords_filtered) >= 50:
                        break
                    if (word not in title_words_set and
                        word not in desc_words_set and
                        word not in keywords_filtered_set):
                        keywords_filtered.append(word)
                        keywords_filtered_set.add(word)
            
            self.log_message.emit(f"    [Metadata] After strategy 1: {len(keywords_filtered)} keywords")
            
            # Strategy 2: Generate variations of existing keywords (if insufficient)
            if len(keywords_filtered) < 50:
                existing_keywords_copy = keywords_filtered.copy()
                for kw in existing_keywords_copy:
                    if len(keywords_filtered) >= 50:
                        break
                    
                    # Plural
                    if not kw.endswith('s') and len(kw) >= 3:
                        plural = kw + 's'
                        if (plural not in title_words_set and
                            plural not in desc_words_set and
                            plural not in keywords_filtered_set and
                            plural not in stop_words):
                            keywords_filtered.append(plural)
                            keywords_filtered_set.add(plural)
                            if len(keywords_filtered) >= 50:
                                break
                    
                    # Singular (remove 's')
                    if kw.endswith('s') and len(kw) > 3:
                        singular = kw[:-1]
                        if (singular not in title_words_set and
                            singular not in desc_words_set and
                            len(singular) >= 3 and
                            singular not in keywords_filtered_set and
                            singular not in stop_words):
                            keywords_filtered.append(singular)
                            keywords_filtered_set.add(singular)
                            if len(keywords_filtered) >= 50:
                                break
                    
                    # Remove endings -ing, -ed, -er, -est, -ly
                    for ending, length in [('ing', 3), ('ed', 2), ('er', 2), ('est', 3), ('ly', 2)]:
                        if len(keywords_filtered) >= 50:
                            break
                        if kw.endswith(ending) and len(kw) > (3 + length):
                            base = kw[:-length]
                            if (base not in title_words_set and
                                base not in desc_words_set and
                                base not in keywords_filtered_set and
                                len(base) >= 3 and
                                base not in stop_words):
                                keywords_filtered.append(base)
                                keywords_filtered_set.add(base)
                                if len(keywords_filtered) >= 50:
                                    break
                    
                    if len(keywords_filtered) >= 50:
                        break
            
            self.log_message.emit(f"    [Metadata] After strategy 2: {len(keywords_filtered)} keywords")
            
            # Strategy 3: Second pass through all_words_filtered for maximum collection
            if len(keywords_filtered) < 50:
                # Go through all words again, including those that might have been missed
                for word in all_words_filtered:
                    if len(keywords_filtered) >= 50:
                        break
                    if (word not in title_words_set and
                        word not in desc_words_set and
                        word not in keywords_filtered_set):
                        keywords_filtered.append(word)
                        keywords_filtered_set.add(word)
            
            self.log_message.emit(f"    [Metadata] After strategy 3: {len(keywords_filtered)} keywords")
            
            # Strategy 4: If still insufficient, пробуем добавить wordsа длиной 2 символа (but not stop words)
            if len(keywords_filtered) < 50:
                meaningful_short_words = {"at", "be", "by", "do", "go", "he", "if", "in", "is", "it", "me", "my", "no", "of", "on", "or", "so", "to", "up", "us", "we"}
                all_words_all_lengths = self.normalize_words(all_text)
                for word in all_words_all_lengths:
                    if len(keywords_filtered) >= 50:
                        break
                    if (len(word) == 2 and
                        word not in meaningful_short_words and
                        word not in stop_words and
                        word not in title_words_set and
                        word not in desc_words_set and
                        word not in keywords_filtered_set):
                        keywords_filtered.append(word)
                        keywords_filtered_set.add(word)
            
            self.log_message.emit(f"    [Metadata] After strategy 4: {len(keywords_filtered)} keywords")
            
            # Final check: if still insufficient, log warning
            if len(keywords_filtered) != 50:
                self.log_message.emit(f"    ⚠ WARNING: Only managed to collect {len(keywords_filtered)} keywords instead of 50. Requirements not met.")
            
            keywords = ', '.join(keywords_filtered[:50])
            
            # STEP 7: Final validation before writing
            title_words_final_set = set(self.normalize_words(title))
            desc_words_final_set = set(self.normalize_words(description))
            keywords_final_set = set([kw.lower() for kw in keywords_filtered])
            
            self.log_message.emit(f"    [Metadata] STEP 7: Финальная валидация...")
            
            # Проверка: title и description не должны иметь общих words (CRITICAL!)
            common_title_desc = title_words_final_set & desc_words_final_set
            if common_title_desc:
                error_msg = f"❌ CRITICAL ERROR: Title and Description contain common words: {common_title_desc}. This violates requirements (0% intersection)."
                self.log_message.emit(f"    {error_msg}")
                self.log_message.emit(f"    [Metadata] Debug information: title='{title[:50]}...', description='{description[:50]}...'")
                raise Exception(error_msg)
            
            # Проверка: description и keywords не должны иметь общих words (CRITICAL!)
            common_desc_kw = desc_words_final_set & keywords_final_set
            if common_desc_kw:
                error_msg = f"❌ CRITICAL ERROR: Description and Keywords contain common words: {common_desc_kw}. This violates requirements (0% intersection)."
                self.log_message.emit(f"    {error_msg}")
                self.log_message.emit(f"    [Metadata] Debug information: description='{description[:50]}...', keywords_count={len(keywords_filtered)}")
                raise Exception(error_msg)
            
            # Проверка: keywords должно быть ровно 50 (CRITICAL!)
            if len(keywords_filtered) != 50:
                error_msg = f"❌ CRITICAL ERROR: Keywords contains {len(keywords_filtered)} words instead of 50. This violates requirements."
                self.log_message.emit(f"    {error_msg}")
                raise Exception(error_msg)
            
            # Проверка: description должен быть 15-80 characters
            if len(description) < 15 or len(description) > 80:
                error_msg = f"❌ CRITICAL ERROR: Description contains {len(description)} characters (requires 15-80). This violates requirements."
                self.log_message.emit(f"    {error_msg}")
                raise Exception(error_msg)
            
            self.log_message.emit(f"    ✓ AI аналfrom завершен: title='{title}' ({len(title_words_final)} words), description='{description[:30]}...' ({len(desc_words_final_set)} уникальных words), keywords={len(keywords_filtered)} words")
            
            return {
                'title': title,
                'description': description,
                'keywords': keywords,
                'category': 'Photography',
                'model_release': 'No'
            }
        
        # Fallback: use basic generation based on filename
        self.log_message.emit(f"    [Metadata] Use basic generation based on filename")
        stem = image_path.stem
        cleaned_stem = self.clean_text(stem)
        
        title = cleaned_stem.replace('_', ' ').replace('-', ' ').title()
        title = ' '.join(title.split())
        
        keywords = self.extract_words(cleaned_stem, max_words=50)
        
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
            'category': 'Photography',
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
        self.setWindowTitle("TagStock PhotoKey - Batch image processing for stock")
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
        folder_group = QGroupBox("Folder with source JPEG files")
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
        output_group = QGroupBox("Folder for saving processed JPEG files")
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
        # Automatic API key by default
        default_api_key = "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"
        self.api_key_edit.setText(default_api_key)
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
        folder = QFileDialog.getExistingDirectory(self, "Select folder with JPEG files")
        if folder:
            self.folder_path_edit.setText(folder)
            self.selected_folder = folder
    
    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder for saving processed JPEG files")
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
                f"Processing completed!\nProcessed JPEG files with metadata saved to output folder."
            )
        else:
            self._processing_stopped = False  # Reset flag
            self.log("[UI] Processing was stopped by user")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = KeyCutterApp()
    window.show()
    sys.exit(app.exec())
