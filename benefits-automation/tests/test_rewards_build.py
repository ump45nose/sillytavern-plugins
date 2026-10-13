import unittest
from platforms.rewards.build import patch_entry


class RewardsBuildTests(unittest.TestCase):
    def test_removes_autonomous_entrypoint_only(self):
        source = "import { checkNodeVersion } from './util/Validator'\nimport Utils, { isBrowserClosedError } from './util/Utils'\nexport class Example {}\nasync function main(): Promise<void> {doSomething()}\nmain().catch(async error => {})\n"
        patched = patch_entry(source)
        self.assertNotIn("doSomething", patched)
        self.assertIn("export class Example", patched)
        self.assertNotIn("checkNodeVersion", patched)

    def test_unrecognized_entrypoint_rejected(self):
        with self.assertRaises(ValueError):
            patch_entry("main()")
