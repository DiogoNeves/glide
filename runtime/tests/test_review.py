import json
import re
import unittest
import test_store
from glide_memory.review import render_review
from glide_memory.store import StoreError


class ReviewTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown
    source = test_store.StoreTests.source
    record = test_store.StoreTests.record
    propose = test_store.StoreTests.propose
    def test_preview_does_not_apply_and_escapes_untrusted_content(self):
        p=self.propose([self.record(body='A quote </script><script>alert(1)</script> must remain text.')])
        before=self.store.export()
        html=render_review(self.store,p['proposal_id'],ui='interactive')
        self.assertEqual(before,self.store.export())
        self.assertNotIn('</script><script>alert(1)',html)
        self.assertIn('sendFollowUpMessage',html)
        self.assertIn('expected_revisions',html)
        encoded=re.search(r'const data = (.*);',html).group(1)
        self.assertEqual(p['records'][0]['body'],json.loads(encoded)['records'][0]['body'])
        self.assertIn('Question or adjust',html)
        self.assertIn('Do not apply this proposal or a replacement',html)
        self.assertIn('This preview has not applied',html)
        self.store.apply(p['proposal_id'])
        with self.assertRaises(StoreError): render_review(self.store,p['proposal_id'])

    def test_text_is_default_and_does_not_apply_while_preserving_evidence_and_revision(self):
        p = self.propose([self.record(claims=[{"id": "qualified", "type": "hypothesis", "text": "Readable labels may help.", "sources": [self.source()], "uncertainty": "The layout may matter too."}])])
        before = self.store.export()
        text = render_review(self.store, p["proposal_id"])
        self.assertNotIn("<script>", text)
        self.assertIn(self.source()["quote"], text)
        self.assertIn(p["rationale"], text)
        self.assertIn("The layout may matter too.", text)
        self.assertIn(p["proposal_id"], text)
        self.assertIn('"thinking": 0', text)
        self.assertIn("question or adjust", text)
        self.assertEqual(before, self.store.export())

    def test_configured_interactive_mode_and_decided_rejections(self):
        self.store.config["review_ui"] = "interactive"
        self.store._save_config()
        p = self.propose()
        self.assertIn("sendFollowUpMessage", render_review(self.store, p["proposal_id"]))
        self.store.apply(p["proposal_id"], decision="rejected")
        with self.assertRaises(StoreError):
            render_review(self.store, p["proposal_id"])
