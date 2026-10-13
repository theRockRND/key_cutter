"""Tests for metadata generation, OpenAI request handling and batch processing (main.py)"""
import csv
import json
import os
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import main  # noqa: E402

FFMPEG_AVAILABLE = shutil.which('ffmpeg') is not None and shutil.which('ffprobe') is not None

KEYWORDS = ("mountain river forest valley stream creek rapids rocks stones moss wilderness nature landscape "
            "scenic outdoors hiking trail travel adventure ecology environment freshwater current flowing "
            "motion pine evergreen woodland canopy fresh pristine tranquil serene calm peaceful daylight "
            "overcast season wild natural remote alpine highland terrain geology erosion splash foam cascade "
            "torrent ravine gorge spruce fir conifer boulders spring summer").split()

AI_RESPONSE = {
    "title": "Mountain River Flowing Through Green Forest Valley",
    "description": "Clear water rushes past mossy boulders under a cloudy summer sky",
    "keywords": ", ".join(KEYWORDS),
}

HD = {'width': 1920, 'height': 1080, 'duration': 12.0}
VERTICAL = {'width': 1080, 'height': 1920, 'duration': 12.0}


def words(text):
    return set(text.lower().replace(',', ' ').split())


LOGS_TMP = tempfile.TemporaryDirectory()


def make_thread(api_key="sk-test", input_folder=".", output_folder="."):
    thread = main.ProcessingThread(input_folder, output_folder, api_key=api_key)
    thread.logs_folder = Path(LOGS_TMP.name)
    thread.logs = []
    thread.log_message.connect(thread.logs.append)
    return thread


def generate(thread, response, video_info=None, rewrite=None):
    """Runs metadata generation with a fixed AI response and an optional fake description rewrite"""
    thread.analyze_image_with_ai = lambda path, info=None: dict(response)
    thread._rewrite_description = mock.Mock(return_value=rewrite)
    return thread.analyze_and_generate_metadata(Path("clip.mov"), video_info)


class FakeOpenAI:
    """Replaces openai.OpenAI: returns queued responses (str) or raises queued exceptions"""

    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        message = types.SimpleNamespace(content=item)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    def client(self, api_key=None):
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=self))


class MetadataRulesTest(unittest.TestCase):
    def setUp(self):
        self.thread = make_thread()

    def check_common_rules(self, metadata):
        title_words = words(metadata['title']) - main.TITLE_CONNECTORS
        desc_words = words(metadata['description'])
        keywords = metadata['keywords'].split(', ')
        self.assertLessEqual(len(keywords), main.MAX_KEYWORDS)
        self.assertEqual(len(keywords), len(set(keywords)), "duplicate keywords")
        self.assertFalse(title_words & desc_words, "title and description share words")
        self.assertFalse(desc_words & set(keywords), "description and keywords share words")
        self.assertTrue(15 <= len(metadata['description']) <= 80)
        self.assertTrue(6 <= len(metadata['title'].split()) <= 10)
        for kw in keywords:
            self.assertRegex(kw, r'^[a-z0-9]{3,}$')
            self.assertNotIn(kw + 's', keywords, f"plural duplicate of {kw}")

    def test_photo_metadata(self):
        metadata = generate(self.thread, AI_RESPONSE)
        self.check_common_rules(metadata)
        self.assertEqual(metadata['title'], "Mountain River Flowing Through Green Forest Valley")
        self.assertEqual(metadata['description'], AI_RESPONSE['description'])
        self.assertEqual(metadata['category'], 'Photography')
        self.assertEqual(len(metadata['keywords'].split(', ')), 49)
        self.assertFalse(set(metadata['keywords'].split(', ')) & words(metadata['title']))

    def test_video_category(self):
        self.assertEqual(generate(self.thread, AI_RESPONSE, HD)['category'], 'Video')

    def test_vertical_video_words(self):
        metadata = generate(self.thread, AI_RESPONSE, VERTICAL)
        self.check_common_rules(metadata)
        self.assertTrue(metadata['title'].endswith("Vertical Video"))
        self.assertEqual(metadata['keywords'].split(', ')[:2], ['vertical', 'video'])

    def test_vertical_title_stays_within_10_words(self):
        response = dict(AI_RESPONSE, title="One Two Three Four Five Six Seven Eight Nine Ten Eleven")
        metadata = generate(self.thread, response, VERTICAL)
        self.assertEqual(len(metadata['title'].split()), 10)
        self.assertTrue(metadata['title'].endswith("Vertical Video"))

    def test_linking_words_kept_in_title(self):
        response = dict(AI_RESPONSE, title="Snow Covered Park Path With Trees And Benches In Winter")
        metadata = generate(self.thread, response)
        self.assertEqual(metadata['title'], "Snow Covered Park Path With Trees and Benches in Winter")
        self.check_common_rules(metadata)

    def test_linking_words_allowed_in_description(self):
        response = dict(AI_RESPONSE, description="Clear water rushes through mossy boulders under a cloudy sky")
        metadata = generate(self.thread, response, HD)
        self.thread._rewrite_description.assert_not_called()
        self.assertEqual(metadata['description'], response['description'])
        self.assertNotIn('through', metadata['keywords'].split(', '))

    def test_no_generated_keyword_variations(self):
        response = dict(AI_RESPONSE, keywords="swings, swing, posts, post, cold, blue, river, winter")
        metadata = generate(self.thread, response)
        keywords = metadata['keywords'].split(', ')
        self.assertIn('swings', keywords)
        self.assertNotIn('swing', keywords)
        self.assertNotIn('post', keywords)
        for invented in ['colds', 'blues', 'wint', 'winters']:
            self.assertNotIn(invented, keywords)

    def test_phrases_in_keywords_are_skipped(self):
        response = dict(AI_RESPONSE, keywords="snowy park, bench, green grass, " + AI_RESPONSE['keywords'])
        keywords = generate(self.thread, response)['keywords'].split(', ')
        self.assertIn('bench', keywords)
        self.assertNotIn('snowy', keywords)

    def test_short_title_padded_from_keywords_not_description(self):
        response = {"title": "Snowman With Stick Arms In Winter Park",
                    "description": "A carrot nosed figure stands amid deep drifts as the camera pulls back",
                    "keywords": "snowman, snow, sticks, twig, carrot, drifts, " + AI_RESPONSE['keywords']}
        metadata = generate(self.thread, response, HD)
        self.assertEqual(metadata['title'], "Snowman With Stick Arms in Winter Park")
        self.assertIn('carrot', metadata['description'])

        response = dict(response, title="Snowman Stick Arms")
        metadata = generate(self.thread, response, HD)
        self.assertEqual(metadata["title"], "Snowman Stick Arms Snow Twig Mountain")  # not "Sticks", not "Drifts"
        self.assertIn('drifts', metadata['description'])  # padding does not take description words

    def test_description_rewrite_when_title_words_used(self):
        response = dict(AI_RESPONSE, description="Clear river water rushes past mossy boulders in the forest")
        rewritten = "Clear water rushes past mossy boulders under a cloudy summer sky"
        metadata = generate(self.thread, response, HD, rewrite=rewritten)
        self.thread._rewrite_description.assert_called_once()
        forbidden = self.thread._rewrite_description.call_args[0][1]
        self.assertIn('river', forbidden)
        self.assertIn('scene', forbidden)  # all generic words are forbidden, not only the found ones
        self.assertEqual(metadata['description'], rewritten)

    def test_description_rewrite_when_too_long(self):
        response = dict(AI_RESPONSE, description="Clear water rushes past mossy boulders under a cloudy summer "
                                                 "sky on a bright morning")
        rewritten = "Clear water rushes past mossy boulders on a bright morning"
        metadata = generate(self.thread, response, HD, rewrite=rewritten)
        self.thread._rewrite_description.assert_called_once()
        self.assertEqual(metadata['description'], rewritten)

    def test_no_rewrite_for_clean_description(self):
        generate(self.thread, AI_RESPONSE, HD)
        self.thread._rewrite_description.assert_not_called()

    def test_title_words_removed_when_rewrite_fails(self):
        response = dict(AI_RESPONSE, description="Clear river water rushes past mossy boulders under a cloudy sky")
        metadata = generate(self.thread, response, HD, rewrite=None)
        self.check_common_rules(metadata)
        self.assertNotIn('river', words(metadata['description']))


class BuildTitleTest(unittest.TestCase):
    def setUp(self):
        self.thread = make_thread()

    def title(self, raw, padding=(), required=()):
        return self.thread.build_title(raw, list(padding), list(required))[0]

    def test_titles_from_real_run(self):
        self.assertEqual(self.title("Railway Tracks And White Car Through A Pine Forest"),
                         "Railway Tracks and White Car Through Pine Forest")
        self.assertEqual(self.title("Young Man Climbs Rocky Mound In Sunny Woodland"),
                         "Young Man Climbs Rocky Mound in Sunny Woodland")
        self.assertEqual(self.title("Historic Railway Yard With Signal Tower And Walking Man"),
                         "Historic Railway Yard With Signal Tower and Walking Man")

    def test_connectors_are_not_title_words(self):
        title, content = self.thread.build_title("Railway Tracks Lead Through Dark Tunnel Toward Daylight", [])
        self.assertEqual(title, "Railway Tracks Lead Through Dark Tunnel Toward Daylight")
        self.assertNotIn('through', content)
        self.assertNotIn('toward', content)

    def test_no_connector_at_edges_or_doubled(self):
        self.assertEqual(self.title("In The Forest Of And Pines Along Rocky Cliffs With", ['moss']),
                         "Forest of Pines Along Rocky Cliffs")

    def test_limit_10_words_without_trailing_connector(self):
        title = self.title("One Two Three Four Five Six Seven Eight Nine And Ten Eleven")
        self.assertEqual(title, "One Two Three Four Five Six Seven Eight Nine")
        title = self.title("One Two Three Four Five Six Seven And Eight Nine", required=['vertical', 'video'])
        self.assertEqual(title, "One Two Three Four Five Six Seven Vertical Video")


class BuildDescriptionTest(unittest.TestCase):
    def setUp(self):
        self.thread = make_thread()

    def test_cuts_before_forbidden_word_instead_of_removing_it(self):
        cases = {
            ("The camera moves along a dim passage toward a sunlit forest", 'toward'):
                "The camera moves along a dim passage",
            ("A moving viewpoint enters sunlit woods as the tunnel fades behind it", 'tunnel'):
                "A moving viewpoint enters sunlit woods",
            ("A moving viewpoint follows a winding path beneath trees and into darkness", 'into'):
                "A moving viewpoint follows a winding path beneath trees",
        }
        for (text, word), expected in cases.items():
            self.assertEqual(self.thread.build_description(text, {word}), expected)

    def test_truncates_before_unfinished_phrase(self):
        cases = {
            "A forward moving shot follows a winding path through sunny woods and rocky hillsides":
                "A forward moving shot follows a winding path through sunny woods",
            "A historic train moves slowly by passengers under sunny skies and wooded hillsides":
                "A historic train moves slowly by passengers under sunny skies",
            "The distant opening grows smaller as the camera moves underground along the rails":
                "The distant opening grows smaller as the camera moves underground",
        }
        for text, expected in cases.items():
            self.assertEqual(self.thread.build_description(text, set()), expected)

    def test_removes_title_and_generic_words(self):
        result = self.thread.build_description("A quiet park scene with snowy trees beside the frozen lake",
                                               {'park', 'trees'})
        self.assertEqual(result, "A quiet with snowy beside the frozen lake")

    def test_strips_dangling_words(self):
        result = self.thread.build_description("Calm water flows past mossy rocks under the", set())
        self.assertEqual(result, "Calm water flows past mossy rocks")

    def test_capitalizes_first_letter(self):
        self.assertEqual(self.thread.build_description("calm water flows past mossy rocks", set()),
                         "Calm water flows past mossy rocks")

    def test_too_short_returns_none(self):
        self.assertIsNone(self.thread.build_description("Snowy park path", {'park'}))
        self.assertIsNone(self.thread.build_description("", set()))


class ParseResponseTest(unittest.TestCase):
    def setUp(self):
        self.thread = make_thread()

    def test_plain_json(self):
        self.assertEqual(self.thread._parse_ai_response(json.dumps(AI_RESPONSE)), AI_RESPONSE)

    def test_markdown_block(self):
        content = "Here you go:\n```json\n" + json.dumps(AI_RESPONSE) + "\n```"
        self.assertEqual(self.thread._parse_ai_response(content), AI_RESPONSE)

    def test_invalid_json(self):
        broken = json.dumps(AI_RESPONSE)[:-20] + '"oops" "x"}'
        self.assertIsNone(self.thread._parse_ai_response(broken))
        self.assertIsNone(self.thread._parse_ai_response("no json here"))


class OpenAIRequestTest(unittest.TestCase):
    def setUp(self):
        self.thread = make_thread()
        self.tmp = tempfile.TemporaryDirectory()
        self.image = Path(self.tmp.name) / 'frame.jpg'
        self.image.write_bytes(b'\xff\xd8fake jpeg')
        sleep_patch = mock.patch.object(main.time, 'sleep')
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_request(self, queue, is_video=False):
        fake = FakeOpenAI(queue)
        with mock.patch.object(main, 'OpenAI', fake.client):
            result = self.thread._analyze_with_openai_api([self.image] * (3 if is_video else 1), "sk-test", is_video)
        return result, fake.calls

    def test_request_parameters(self):
        result, calls = self.run_request([json.dumps(AI_RESPONSE)], is_video=True)
        self.assertEqual(result, AI_RESPONSE)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call['model'], 'gpt-6-luna')
        self.assertEqual(call['reasoning_effort'], 'none')
        self.assertEqual(call['response_format'], {"type": "json_object"})
        content = call['messages'][0]['content']
        self.assertEqual(sum(1 for part in content if part['type'] == 'image_url'), 3)
        self.assertIn('ONE stock video clip', content[0]['text'])

    def test_retry_on_invalid_json(self):
        result, calls = self.run_request(["{broken", json.dumps(AI_RESPONSE)])
        self.assertEqual(result, AI_RESPONSE)
        self.assertEqual(len(calls), 2)

    def test_none_after_two_invalid_responses(self):
        result, calls = self.run_request(["{broken", "{broken"])
        self.assertIsNone(result)
        self.assertEqual(len(calls), 2)

    def test_retry_on_temporary_error(self):
        result, calls = self.run_request([Exception("Error code: 500 - server error"), json.dumps(AI_RESPONSE)])
        self.assertEqual(result, AI_RESPONSE)
        self.assertEqual(len(calls), 2)

    def test_rate_limit_waits_and_retries(self):
        result, _ = self.run_request([Exception("Error code: 429 - Rate limit reached"), json.dumps(AI_RESPONSE)])
        self.assertEqual(result, AI_RESPONSE)
        main.time.sleep.assert_called_with(60)

    def test_fatal_error_is_raised(self):
        for error in ["Error code: 401 - Incorrect API key provided", "Error code: 429 - insufficient_quota"]:
            with self.assertRaises(main.FatalAPIError):
                self.run_request([Exception(error)])

    def test_is_fatal_api_error(self):
        self.assertTrue(main.is_fatal_api_error("Error code: 401 - invalid_api_key"))
        self.assertTrue(main.is_fatal_api_error("You exceeded your current quota: insufficient_quota"))
        self.assertFalse(main.is_fatal_api_error("Error code: 429 - Rate limit reached"))
        self.assertFalse(main.is_fatal_api_error("Error code: 500"))


class RewriteDescriptionTest(unittest.TestCase):
    def setUp(self):
        self.thread = make_thread()

    def rewrite(self, queue, forbidden=('park', 'scene')):
        fake = FakeOpenAI(queue)
        with mock.patch.object(main, 'OpenAI', fake.client):
            result = self.thread._rewrite_description("A quiet park scene in winter", list(forbidden))
        return result, fake.calls

    def test_clean_rewrite(self):
        result, calls = self.rewrite(["A quiet snowy garden on a calm winter day"])
        self.assertEqual(result, "A quiet snowy garden on a calm winter day")
        self.assertEqual(len(calls), 1)
        self.assertIn('park, scene', calls[0]['messages'][0]['content'])

    def test_retry_when_forbidden_word_remains(self):
        result, calls = self.rewrite(["A quiet winter scene", "A quiet snowy garden on a calm winter day"])
        self.assertEqual(result, "A quiet snowy garden on a calm winter day")
        self.assertEqual(len(calls), 2)

    def test_retry_when_too_long(self):
        long_text = "A quiet snowy garden " * 5
        result, calls = self.rewrite([long_text, "A quiet snowy garden on a calm winter day"])
        self.assertEqual(result, "A quiet snowy garden on a calm winter day")
        self.assertEqual(len(calls), 2)

    def test_three_attempts_with_feedback(self):
        result, calls = self.rewrite(["A quiet park", "A calm park in snow", "A quiet snowy garden on a calm winter day"])
        self.assertEqual(result, "A quiet snowy garden on a calm winter day")
        self.assertEqual(len(calls), 3)
        feedback = calls[1]['messages'][-1]['content']
        self.assertIn('park', feedback)
        self.assertEqual(calls[1]['messages'][-2], {"role": "assistant", "content": "A quiet park"})

    def test_best_attempt_returned_when_none_is_clean(self):
        too_long = "A quiet snowy garden with frosted hedges and benches on a calm and bright winter day"
        result, calls = self.rewrite(["A quiet park scene", too_long, "A park in snow"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(result, too_long)  # no forbidden words: only too long, cut in code later

    def test_error_returns_none(self):
        result, _ = self.rewrite([Exception("Error code: 500")])
        self.assertIsNone(result)

    def test_no_api_key(self):
        thread = make_thread(api_key=None)
        with mock.patch.dict(os.environ, {}, clear=True):
            thread.api_key = None
            self.assertIsNone(thread._rewrite_description("text", ['park']))


class CleanTextTest(unittest.TestCase):
    def test_hyphen_separates_words(self):
        thread = make_thread()
        self.assertEqual(thread.clean_text("A forward-facing shot of old\u2014fashioned cars/trains!"),
                         "A forward facing shot of old fashioned cars trains")


class KeychainTest(unittest.TestCase):
    def test_save_and_load(self):
        storage = {}
        fake_keyring = types.SimpleNamespace(
            set_password=lambda service, user, value: storage.__setitem__((service, user), value),
            get_password=lambda service, user: storage.get((service, user)))
        with mock.patch.object(main, 'keyring', fake_keyring, create=True), \
                mock.patch.object(main, 'KEYRING_AVAILABLE', True):
            self.assertIsNone(main.load_saved_api_key())
            self.assertTrue(main.save_api_key("sk-saved"))
            self.assertEqual(main.load_saved_api_key(), "sk-saved")
            self.assertEqual(list(storage), [(main.KEYRING_SERVICE, main.KEYRING_USER)])

    def test_keychain_errors_are_handled(self):
        def fail(*args):
            raise RuntimeError("keychain locked")
        fake_keyring = types.SimpleNamespace(set_password=fail, get_password=fail)
        with mock.patch.object(main, 'keyring', fake_keyring, create=True), \
                mock.patch.object(main, 'KEYRING_AVAILABLE', True):
            self.assertIsNone(main.load_saved_api_key())
            self.assertFalse(main.save_api_key("sk-x"))

    def test_keyring_not_installed(self):
        with mock.patch.object(main, 'KEYRING_AVAILABLE', False):
            self.assertIsNone(main.load_saved_api_key())
            self.assertFalse(main.save_api_key("sk-x"))

    def test_no_hardcoded_api_key(self):
        source = Path(main.__file__).read_text()
        self.assertNotRegex(source, r'sk-(proj-)?[A-Za-z0-9_-]{20,}')


@unittest.skipUnless(FFMPEG_AVAILABLE, "ffmpeg/ffprobe not installed")
class BatchProcessingTest(unittest.TestCase):
    """End-to-end run() with generated clips and a stubbed AI"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.input = Path(cls.tmp.name) / 'in'
        cls.input.mkdir()

        def clip(name, size, rate, duration):
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc=size={size}:rate={rate}',
                            '-t', str(duration), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(cls.input / name)],
                           check=True)

        clip('a_ok.mp4', '1920x1080', 25, 6)
        clip('b_vertical.mov', '1080x1920', 30, 6)
        clip('c_720p.mp4', '1280x720', 25, 6)
        clip('d_short.mp4', '1920x1080', 25, 3)
        from PIL import Image
        Image.new('RGB', (64, 48), 'red').save(cls.input / 'e_photo.jpg')
        (cls.input / 'notes.txt').write_text('ignored')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.output = Path(tempfile.mkdtemp(dir=self.tmp.name))
        sleep_patch = mock.patch.object(main.time, 'sleep')
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def run_batch(self, analyze):
        thread = make_thread(input_folder=str(self.input), output_folder=str(self.output))
        thread.analyze_image_with_ai = analyze
        thread._rewrite_description = mock.Mock(return_value=None)
        thread.write_iptc_with_exiftool = mock.Mock(side_effect=FileNotFoundError)
        thread.run()
        return thread

    def read_csv(self):
        with open(self.output / main.VIDEO_CSV_NAME, newline='', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    def test_batch(self):
        before = {p.name: p.stat().st_mtime for p in self.input.iterdir()}
        thread = self.run_batch(lambda path, info=None: dict(AI_RESPONSE))

        rows = self.read_csv()
        self.assertEqual([r['Filename'] for r in rows], ['a_ok.mp4', 'b_vertical.mov'])
        self.assertEqual(list(rows[0].keys()), ['Filename', 'Title', 'Keywords', 'Category', 'Releases'])
        self.assertTrue(rows[1]['Title'].endswith('Vertical Video'))
        self.assertTrue(rows[1]['Keywords'].startswith('vertical, video'))

        # Videos are not copied, photo is copied with metadata
        self.assertEqual(sorted(p.name for p in self.output.iterdir()), [main.VIDEO_CSV_NAME, 'e_photo.jpg'])
        self.assertEqual(before, {p.name: p.stat().st_mtime for p in self.input.iterdir()})

        log = '\n'.join(thread.logs)
        self.assertIn('Files found: 1 JPEG, 4 video', log)
        # Log of the run is saved to a file in the logs folder, not in the output folder
        self.assertEqual(thread.log_file_path.parent, thread.logs_folder)
        self.assertRegex(thread.log_file_path.name, r'^run_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log$')
        saved = thread.log_file_path.read_text(encoding='utf-8')
        self.assertIn(f'TagStock PhotoKey {main.__version__}', saved)
        self.assertIn('Files found: 1 JPEG, 4 video', saved)
        self.assertIn(f'Log saved to: {thread.log_file_path}', saved)
        self.assertIn('c_720p.mp4: width 1280px is below minimum 1920px', log)
        self.assertIn('d_short.mp4: duration 3.00s is out of range 5-60s', log)

    def test_failed_file_is_skipped(self):
        def analyze(path, info=None):
            if path.name == 'a_ok.mp4':
                raise Exception("ERROR: No valid response from AI after 2 attempts")
            return dict(AI_RESPONSE)

        thread = self.run_batch(analyze)
        self.assertEqual([r['Filename'] for r in self.read_csv()], ['b_vertical.mov'])
        log = '\n'.join(thread.logs)
        self.assertIn('Files skipped (metadata generation failed, run again to retry): 1', log)
        self.assertIn('Processed files: 2 of 5', log)

    def test_failed_photo_copy_is_removed(self):
        def analyze(path, info=None):
            if path.suffix == '.jpg':
                raise Exception("ERROR: No valid response from AI after 2 attempts")
            return dict(AI_RESPONSE)

        self.run_batch(analyze)
        self.assertFalse((self.output / 'e_photo.jpg').exists())

    def test_fatal_error_stops_batch(self):
        calls = []

        def analyze(path, info=None):
            calls.append(path.name)
            raise main.FatalAPIError("OpenAI API error: Error code: 401")

        finished = []
        thread = make_thread(input_folder=str(self.input), output_folder=str(self.output))
        thread.analyze_image_with_ai = analyze
        thread.finished.connect(finished.append)
        thread.run()
        self.assertEqual(calls, ['a_ok.mp4'])
        self.assertIn('Processing stopped: check API key and balance', '\n'.join(thread.logs))
        self.assertEqual(finished, [[]])  # finished is emitted once, after the log file is saved
        self.assertIn('Processing stopped: check API key and balance', thread.log_file_path.read_text())

    def test_csv_is_recreated_on_new_run(self):
        self.run_batch(lambda path, info=None: dict(AI_RESPONSE))
        self.run_batch(lambda path, info=None: dict(AI_RESPONSE))
        self.assertEqual(len(self.read_csv()), 2)


if __name__ == '__main__':
    unittest.main()
