#!/usr/bin/env python3
"""Prepare a clean, pinned SubBoost build context; never read production credentials."""
import argparse
import io
import pathlib
import shutil
import tarfile
import urllib.request

UPSTREAM = "4a69b494b46d095c965be58cf425fe35a2c1e524"
HERE = pathlib.Path(__file__).resolve().parent


def replace_once(path, before, after):
    source = path.read_text()
    if source.count(before) != 1:
        raise RuntimeError("Pinned upstream patch no longer applies: " + str(path))
    path.write_text(source.replace(before, after, 1))


def prepare(destination):
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise RuntimeError("Build destination must be empty")
    url = "https://codeload.github.com/SubBoost/subboost/tar.gz/" + UPSTREAM
    data = urllib.request.urlopen(url, timeout=60).read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            parts = pathlib.PurePosixPath(member.name).parts
            if len(parts) <= 1:
                continue
            if ".." in parts or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise RuntimeError("Unexpected archive entry")
            member.name = str(pathlib.PurePosixPath(*parts[1:]))
            archive.extract(member, destination)

    for filename in ("android-tailscale.ts", "android-tailscale.json", "android-tailscale.test.ts"):
        shutil.copy2(HERE / filename, destination / "local/src/lib" / filename)
    route = destination / "local/app/api/subscriptions/[id]/config.yaml/route.ts"
    replace_once(route, 'import { apiError } from "@local/lib/http";',
                 'import { apiError } from "@local/lib/http";\n'
                 'import { ANDROID_TAILSCALE_PROFILE, applyAndroidTailscaleProfile } from "@local/lib/android-tailscale";')
    replace_once(route, '  return new Response(result.yaml, {',
                 '  const profile = new URL(request.url).searchParams.get("profile");\n'
                 '  if (profile && profile !== ANDROID_TAILSCALE_PROFILE) {\n'
                 '    return apiError("Unknown subscription profile.", "BAD_REQUEST", 400);\n'
                 '  }\n'
                 '  let yaml = result.yaml;\n'
                 '  if (profile === ANDROID_TAILSCALE_PROFILE) {\n'
                 '    try { yaml = applyAndroidTailscaleProfile(yaml); }\n'
                 '    catch { return apiError("Unable to generate Android Tailscale profile.", "CONFIGURATION_ERROR", 500); }\n'
                 '  }\n'
                 '  return new Response(yaml, {')
    tests = destination / "local/app/api/subscriptions/[id]/config.yaml/route.test.ts"
    tests.write_text(tests.read_text() + '\n' + (HERE / "route-tests.ts.txt").read_text())
    # Limit Next build workers on the NAS; this does not change request handling.
    replace_once(destination / "local/next.config.mjs", '  output: "standalone",',
                 '  output: "standalone",\n  experimental: { cpus: 1 },')
    shutil.copy2(HERE / "Dockerfile", destination / "Dockerfile")
    print("Prepared pinned SubBoost source:", destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=pathlib.Path)
    prepare(parser.parse_args().destination.resolve())
