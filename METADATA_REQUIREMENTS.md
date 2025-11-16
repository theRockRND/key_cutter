# METADATA REQUIREMENTS FOR STOCK IMAGES

## TITLE

### Main Requirements:
- ✅ **Generation based on image analysis** - title is formed exclusively based on AI analysis of image content
- ✅ **Maximum 10 words** - title must contain no more than 10 words
- ✅ **No word repetitions** - each word in title must be unique (not repeated)
- ✅ **English text only** - no other languages
- ✅ **No special characters** - only English letters, numbers and spaces
- ✅ **Uniqueness** - title should not repeat for different images (previous title is tracked)
- ✅ **Format** - each word with capital letter (Title Case)

### Excluded words (stop words):
- Articles: the, a, an
- Prepositions: of, in, on, at, to, for, with
- Linking verbs: is, are, was, were
- Conjunctions: and, or, but
- Demonstrative pronouns: this, that, these, those
- Personal pronouns: it, its, they, them, what, you
- Common words: see, image, photography, photo, picture, detailed, describe, scene, happening, showing, view

### Data Source:
- Only words from AI image analysis (captions from BLIP model)
- Predefined lists or templates are NOT used

---

## DESCRIPTION

### Main Requirements:
- ✅ **Generation based on image analysis** - description is formed exclusively based on AI analysis of image content
- ✅ **Must NOT repeat title** - CRITICALLY IMPORTANT: description must NOT contain words already used in title
- ✅ **Must NOT contain keywords** - CRITICALLY IMPORTANT: description must NOT contain words used in keywords
- ✅ **Maximum 80 characters** - strict length limit
- ✅ **Minimum 15 characters** - description must be informative
- ✅ **English text only** - no other languages
- ✅ **No special characters** - only English letters, numbers and spaces
- ✅ **Uniqueness** - description should not repeat for different images (previous description is tracked)
- ✅ **Informativeness** - must contain information about the photo, be unique and informative
- ✅ **Format** - first letter capital, rest lowercase (Capitalize)

### Prohibited phrases (general phrases):
- ❌ "Professional photography image"
- ❌ "High quality professional image"
- ❌ "Detailed view of scene"
- ❌ "Scene showing detailed view"
- ❌ "Scene with various elements"
- ❌ "View showing scene details"
- ❌ "Detailed scene view"
- ❌ "Scene"
- ❌ "Scene details"
- ❌ "High quality"
- ❌ "Professional image"

### Excluded words (stop words):
- Articles: the, a, an
- Prepositions: of, in, on, at, to, for, with
- Linking verbs: is, are, was, were
- Conjunctions: and, or, but
- Demonstrative pronouns: this, that, these, those
- Personal pronouns: it, its, they, them, what, you
- Common words: see, image, photography, photo, picture, detailed, describe, scene, happening, list, main, objects, colors, elements, professional, showing, view, high, quality

### Data Source:
- Only words from AI image analysis (captions from BLIP model)
- Words from title are excluded
- Words from keywords are excluded
- Predefined lists or templates are NOT used

---

## KEYWORDS

### Main Requirements:
- ✅ **Exactly 50 words** - CRITICALLY IMPORTANT: keywords must contain exactly 50 individual words
- ✅ **Only individual words** - each keyword must be a single word (not a phrase)
- ✅ **Generation based on image analysis** - keywords are formed EXCLUSIVELY based on the analyzed image
- ✅ **NOT taken from title** - keywords must NOT contain words already used in title
- ✅ **NOT taken from description** - CRITICALLY IMPORTANT: keywords must NOT contain words used in description
- ✅ **English text only** - no other languages
- ✅ **No special characters** - only English letters, numbers (cleaned from all special characters)
- ✅ **Uniqueness** - each word in keywords must be unique (not repeated)
- ✅ **Minimum 3 characters** - each word must contain at least 3 characters
- ✅ **Format** - all words lowercase, separated by comma and space (", ")

### Excluded words (stop words):
- Articles: the, a, an
- Prepositions: of, in, on, at, to, for, with
- Linking verbs: is, are, was, were
- Conjunctions: and, or, but
- Demonstrative pronouns: this, that, these, those
- Personal pronouns: it, its, they, them, what, you
- Common words: see, image, photography, photo, picture, shot, capture, professional, high, quality, detailed, sharp, clear, vibrant, colorful, bright, beautiful, stunning, amazing, artistic, creative, closeup, macro, wide, angle, vertical, horizontal, portrait, landscape, background, foreground, focus, blur, bokeh, depth, field, composition, framing, lighting, natural, light, sunlight, shadow, highlight, contrast, saturation, hue, tone, texture, pattern, detail, describe, list, main, objects, colors, scene, elements

### Data Source:
- ONLY words from AI image analysis (captions from BLIP model)
- Predefined lists (color_keywords, nature_keywords, etc.) are NOT used
- Templates or common words are NOT used
- After generating description, all words present in description are removed from keywords

### Generation Process:
1. Collect all words from all image descriptions (captions)
2. Clean from stop words
3. Clean from special characters
4. Split phrases into individual words (if any)
5. Remove duplicates
6. Supplement to 50 words from all available sources (multiple passes through descriptions)
7. After generating description - remove words from keywords that are in description
8. Supplement to 50 words after filtering

---

## GENERAL REQUIREMENTS

### Data Source for All Fields:
- ✅ All metadata is generated based on AI image analysis
- ✅ Local BLIP model or external APIs (OpenAI, custom) are used
- ✅ Model analyzes image content and generates descriptions
- ✅ Words for title, description and keywords are extracted from these descriptions

### Field Relationships:
- ✅ Title and Description - must NOT have common words
- ✅ Description and Keywords - must NOT have common words
- ✅ Title and Keywords - may have common words (but preferably avoid)

### Recording Format:
- ✅ All metadata is written directly to JPEG files via EXIF/IPTC
- ✅ Stock platforms automatically pull data when uploading

---

## EXAMPLES

### ❌ INCORRECT:

**Title:** "Small Bird Standing Next Door"  
**Description:** "Small bird standing next door" ← repeats title!  
**Keywords:** "happening" ← only 1 word instead of 50!

---

### ✅ CORRECT:

**Title:** "Small Bird Standing Next Door"  
**Description:** "Perched on wooden surface near entrance" ← unique words, not from title  
**Keywords:** "bird, small, standing, door, next, wooden, surface, perched, entrance, outdoor, nature, wildlife, animal, feather, beak, eye, branch, tree, green, brown, gray, white, black, colorful, vibrant, natural, wild, free, flying, resting, calm, peaceful, quiet, serene, beautiful, cute, tiny, little, delicate, fragile, gentle, soft, smooth, textured, detailed, sharp, clear, bright, sunny, daylight, morning" ← exactly 50 words

---

## NOTES

- All requirements are strictly followed in the code
- If any requirement is violated, a warning is generated in logs
- If it's impossible to generate 50 keywords due to short analysis, a warning is displayed
- Description is always checked for common phrases and recreated if necessary

