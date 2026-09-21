import copy
import pathlib
import tempfile
import unittest
from publish_manifest import make_manifest, metadata_from_badging


class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.apk = pathlib.Path(self.temp.name) / "app-beta.apk"
        self.apk.write_bytes(b"fixture apk bytes")
        self.previous = {"schemaVersion": 1, "channel": "beta",
                         "applicationId": "com.andinem.audioguitartuner.beta", "latest": None}
        self.release = {"draft": False, "prerelease": True, "published_at": "2026-09-21T00:00:00Z",
                        "tag_name": "v3.5.0-beta12", "body": "Описание",
                        "assets": [{"name": self.apk.name, "state": "uploaded", "size": self.apk.stat().st_size,
                                    "browser_download_url": "https://github.com/ant0n-56/AudioGuitarTuner-updates/releases/download/v3.5.0-beta12/app-beta.apk"}]}
        self.badging = "package: name='com.andinem.audioguitartuner.beta' versionCode='33' versionName='3.5.0-beta12'"
        self.signers = {"beta": "a" * 64}

    def make(self, **kw):
        return make_manifest(kw.get("release", self.release), self.apk, kw.get("badging", self.badging),
                             kw.get("certificate", "a" * 64), self.signers, kw.get("previous", self.previous))

    def test_version_and_channel_come_from_apk(self):
        result = self.make()
        self.assertEqual(33, result["latest"]["versionCode"])
        self.assertEqual("Описание", result["latest"]["releaseNotes"])
        self.assertEqual(64, len(result["latest"]["sha256"]))
        self.assertEqual(result, self.make(previous=result))

    def test_drafts_wrong_channel_and_tag_are_rejected(self):
        for changes in ({"draft": True}, {"published_at": None}, {"prerelease": False},
                        {"tag_name": "v3.6.0"}, {"prerelease": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.make(release=dict(self.release, **changes))
        with self.assertRaises(ValueError):
            self.make(badging=self.badging.replace(".beta'", "'"))

    def test_invalid_assets_and_notes_are_rejected(self):
        for modify in (lambda r: r["assets"].clear(), lambda r: r["assets"].append(r["assets"][0].copy()),
                       lambda r: r["assets"][0].update(size=1),
                       lambda r: r["assets"][0].update(browser_download_url="https://example.com/app.apk"),
                       lambda r: r["assets"][0].update(digest="sha256:" + "b" * 64),
                       lambda r: r.update(body="x" * 12001)):
            release = copy.deepcopy(self.release)
            modify(release)
            with self.assertRaises(ValueError):
                self.make(release=release)

    def test_certificate_and_downgrade_protection(self):
        with self.assertRaises(ValueError):
            self.make(certificate="b" * 64)
        old = self.make()
        old["latest"]["versionCode"] = 34
        with self.assertRaises(ValueError):
            self.make(previous=old)
        old["latest"]["versionCode"] = 33
        old["latest"]["sha256"] = "b" * 64
        with self.assertRaises(ValueError):
            self.make(previous=old)

    def test_bad_apk_metadata(self):
        for value in ("0", "-1", "2147483648"):
            with self.assertRaises(ValueError):
                metadata_from_badging(self.badging.replace("versionCode='33'", f"versionCode='{value}'"))

    def test_stable_channel_uses_production_package_and_plain_version(self):
        self.signers["stable"] = "a" * 64
        previous = dict(self.previous, channel="stable", applicationId="com.andinem.audioguitartuner")
        release = copy.deepcopy(self.release)
        release.update(prerelease=False, tag_name="v3.5.0")
        release["assets"][0]["browser_download_url"] = release["assets"][0]["browser_download_url"].replace("-beta12/", "/")
        badging = self.badging.replace(".beta'", "'").replace("3.5.0-beta12", "3.5.0")
        self.assertEqual("stable", self.make(release=release, badging=badging, previous=previous)["channel"])


if __name__ == "__main__":
    unittest.main()
