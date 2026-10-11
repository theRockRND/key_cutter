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
- ✅ **Natural sentence from image analysis** - the AI writes one grammatical sentence; it is kept as a phrase (not rebuilt from separate words)
- ✅ **Must NOT repeat title** - CRITICALLY IMPORTANT: if the AI sentence uses title (or generic) words, a second text-only request asks the AI to rewrite it without them; any remaining title words are removed
- ✅ **Must NOT share words with keywords** - CRITICALLY IMPORTANT: description words are removed from keywords
- ✅ **15-80 characters, more than 5 words** - a longer sentence is rewritten by the AI; truncation at a word boundary is only a fallback and never ends with an article or preposition
- ✅ **English text only, no special characters**
- ✅ **Format** - first letter capital
- ✅ Articles and prepositions (a, the, on, with...) are allowed for grammar

### Removed generic words:
- see, image, photography, photo, picture, detailed, describe, scene, happening, showing, view, professional, high, quality, list, main, objects, colors, elements

### Fallback:
- If fewer than 6 words remain after removing title words, description is built from analysis words (without title words)

---

## KEYWORDS

### Main Requirements:
- ✅ **Up to 49 words** - Adobe Stock limit; the AI is asked for 65 words so that enough remain after filtering
- ✅ **Warning below 25 words** - fewer keywords are written as is, processing continues
- ✅ **Only real words from AI analysis** - no generated variations (adding "s", cutting endings)
- ✅ **Only individual words** - phrases from AI are skipped
- ✅ **NOT taken from title**, **NOT taken from description**
- ✅ **No singular/plural duplicates** (swing / swings)
- ✅ **Unique, minimum 3 characters, lowercase, separated by ", "**
- ✅ **Order** - AI order (most relevant first), then other words from AI title/description analysis
- ✅ **Vertical video** - starts with "vertical, video"

### Excluded words (stop words):
- Articles, prepositions, linking verbs, conjunctions, pronouns: the, a, an, of, in, on, at, to, for, with, is, are, was, were, and, or, but, this, that, these, those, it, its, they, them, what, you, by, from, as, be, have, has, had, do, does, did, will, would, could, should, may, might, must, can, up, out, so, if, no, not, only, just, more, most, very, much, many, some, any, all, each, every, both, such, than, too, also, here, there, where, when, why, how, who, which, whose, whom
- Common words: see, image, photography, photo, picture, detailed, describe, scene, happening, showing, view, professional, high, quality

---

## GENERAL REQUIREMENTS

### Data Source for All Fields:
- ✅ All metadata is generated based on AI image analysis
- ✅ OpenAI model `gpt-6-luna` is used
- ✅ Model analyzes image content and generates descriptions
- ✅ Words for title, description and keywords are extracted from these descriptions

### Field Relationships:
- ✅ Title and Description - must NOT have common words
- ✅ Description and Keywords - must NOT have common words
- ✅ Title and Keywords - no common words (except "vertical, video" for vertical clips)

### Recording Format:
- ✅ All metadata is written directly to JPEG files via EXIF/IPTC
- ✅ Stock platforms automatically pull data when uploading

---

## VIDEO

- ✅ Video is analyzed through 3 frames (25%, 50%, 75% of the clip); Title/Description/Keywords follow the same rules as photos
- ✅ **Vertical clips** - title ends with "Vertical Video", keywords start with "vertical, video" (Adobe Stock requirement); these words are never used in description
- ✅ Clips not meeting Adobe Stock technical requirements are skipped (see README, section "Video (Adobe Stock)")
- ✅ Video files are not copied or modified - metadata is saved only to `adobe_stock_videos.csv` in the output folder (Adobe Stock CSV upload)

---

## EXAMPLES

### ❌ INCORRECT:

**Title:** "Small Bird Standing Next Door"  
**Description:** "Small bird standing next door" ← repeats title!  
**Keywords:** "swing, swings, wint, snowys, colds" ← duplicates and invented words!

---

### ✅ CORRECT:

**Title:** "Small Bird Standing Next Door"  
**Description:** "Perched on a wooden surface near the entrance" ← natural sentence, no title words  
**Keywords:** "wildlife, animal, feather, beak, branch, tree, garden, brown, gray, outdoor, nature, tiny, cute, calm, ..." ← up to 49 real words, none from title or description

---

## NOTES

- All requirements are strictly followed in the code
- If any requirement is violated, a warning is generated in logs
- If fewer than 25 keywords remain after filtering, a warning is displayed
- Description is always checked for common phrases and recreated if necessary

