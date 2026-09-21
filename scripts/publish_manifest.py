"""Create a channel feed from an already published, signed APK; no APK installation."""
import argparse
import hashlib
import json
import pathlib
import re
import subprocess

REPOSITORY = "ant0n-56/AudioGuitarTuner-updates"
PACKAGES = {"stable": "com.andinem.audioguitartuner", "beta": "com.andinem.audioguitartuner.beta"}


def metadata_from_badging(text):
    line = next((line for line in text.splitlines() if line.startswith("package: ")), "")
    fields = dict(re.findall(r"(\w+)='([^']*)'", line))
    code = int(fields["versionCode"])
    if not 0 < code <= 2147483647:
        raise ValueError("Invalid versionCode")
    return fields["name"], code, fields["versionName"]


def make_manifest(release, apk, badging, certificate, expected_signers, previous):
    if release.get("draft") is not False or not release.get("published_at"):
        raise ValueError("Only published releases can update a channel")
    if type(release.get("prerelease")) is not bool:
        raise ValueError("Missing prerelease flag")
    channel = "beta" if release["prerelease"] else "stable"
    package, code, name = metadata_from_badging(badging)
    version_pattern = r"\d+\.\d+\.\d+-beta\d+" if channel == "beta" else r"\d+\.\d+\.\d+"
    if package != PACKAGES[channel] or not re.fullmatch(version_pattern, name):
        raise ValueError("APK package/version does not belong to release channel")
    tag = release["tag_name"]
    if tag != "v" + name:
        raise ValueError("Release tag must match APK versionName")
    expected_signer = expected_signers.get(channel)
    if not expected_signer or certificate != expected_signer:
        raise ValueError("APK signing certificate is not configured or does not match channel")
    assets = [a for a in release.get("assets", []) if a["name"].endswith(".apk")]
    if len(assets) != 1:
        raise ValueError("Attach exactly one APK to the release")
    asset = assets[0]
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.apk", asset["name"]) or asset["name"] != apk.name:
        raise ValueError("Unexpected APK filename")
    url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{apk.name}"
    if asset.get("state") != "uploaded" or asset.get("browser_download_url") != url:
        raise ValueError("APK must be an uploaded asset in the public distribution repository")
    if not 0 < apk.stat().st_size <= 100 * 1024 * 1024 or asset.get("size") != apk.stat().st_size:
        raise ValueError("APK size mismatch or limit exceeded")
    digest = hashlib.sha256(apk.read_bytes()).hexdigest()
    remote_digest = asset.get("digest")
    if remote_digest and remote_digest != "sha256:" + digest:
        raise ValueError("GitHub asset digest does not match APK")
    notes = release.get("body") or ""
    if not isinstance(notes, str) or len(notes) > 12000:
        raise ValueError("Release notes exceed 12000 characters")
    if previous.get("schemaVersion") != 1 or previous.get("channel") != channel or previous.get("applicationId") != package:
        raise ValueError("Invalid existing channel manifest")
    old = previous.get("latest")
    if old:
        if code < old["versionCode"]:
            raise ValueError("Refusing channel downgrade")
        if code == old["versionCode"] and (digest != old["sha256"] or url != old["apkUrl"] or name != old["versionName"]):
            raise ValueError("A versionCode cannot be reused for different APKs")
    latest = {"versionCode": code, "versionName": name, "releaseNotes": notes,
              "apkUrl": url, "sha256": digest}
    return {"schemaVersion": 1, "channel": channel, "applicationId": package, "latest": latest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-json", required=True, type=pathlib.Path)
    parser.add_argument("--apk-dir", required=True, type=pathlib.Path)
    parser.add_argument("--aapt", required=True)
    parser.add_argument("--apksigner", required=True)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("."))
    args = parser.parse_args()
    release = json.loads(args.release_json.read_text(encoding="utf-8-sig"))
    apks = list(args.apk_dir.glob("*.apk"))
    if len(apks) != 1:
        raise ValueError("Expected exactly one downloaded APK")
    apk = apks[0]
    badging = subprocess.check_output([args.aapt, "dump", "badging", str(apk)], text=True, encoding="utf-8")
    certs = subprocess.check_output([args.apksigner, "verify", "--print-certs", str(apk)], text=True, encoding="utf-8")
    fingerprints = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([a-fA-F0-9]{64})", certs)
    if len(fingerprints) != 1:
        raise ValueError("Expected one verified APK signer")
    channel = "beta" if release.get("prerelease") else "stable"
    target = args.root / "channels" / (channel + ".json")
    previous = json.loads(target.read_text(encoding="utf-8"))
    signers = json.loads((args.root / "signers.json").read_text(encoding="utf-8"))
    manifest = make_manifest(release, apk, badging, fingerprints[0].lower(), signers, previous)
    # Validation completes before replacing the public feed.
    pending = target.with_suffix(".tmp")
    pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(target)
    if channel == "stable":
        latest = manifest["latest"]
        legacy = {"versionCode": latest["versionCode"], "versionName": latest["versionName"],
                  "updateUrl": latest["apkUrl"], "releaseNotes": latest["releaseNotes"]}
        (args.root / "channels" / "legacy-update.json").write_text(
            json.dumps(legacy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {channel}: {manifest['latest']['versionName']} ({manifest['latest']['versionCode']})")


if __name__ == "__main__":
    main()
