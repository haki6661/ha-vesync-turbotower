"""Check whether upstream has caught up with this fork.

Writes findings as `key=value` lines to $GITHUB_OUTPUT:

- pr_state: state of webdjoe/pyvesync#552 (open, closed, merged)
- core_version: latest stable Home Assistant release
- core_pyvesync: pyvesync version that release requires
- core_supported: "true" if that pyvesync version knows the Turbo Tower Pro
- pypi_latest: latest pyvesync release on PyPI
- pypi_supported: "true" if that release knows the Turbo Tower Pro
- harness: newest pytest-homeassistant-custom-component (may pin a HA beta)
- harness_ha: the Home Assistant version that harness pins
"""

import io
import json
import os
import re
import urllib.request
import zipfile

MODEL = "CAF-DC111S"
TOKEN = os.environ.get("GITHUB_TOKEN", "")


def get(url: str) -> bytes:
    """Fetch a URL, authenticated for the GitHub API."""
    request = urllib.request.Request(url, headers={"User-Agent": "watch-upstream"})
    if TOKEN and url.startswith("https://api.github.com/"):
        request.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def get_json(url: str) -> dict:
    """Fetch and parse JSON."""
    return json.loads(get(url))


def pyvesync_supports(version: str) -> bool:
    """Download a pyvesync wheel and look for the model in its device map."""
    release = get_json(f"https://pypi.org/pypi/pyvesync/{version}/json")
    wheel = next(u["url"] for u in release["urls"] if u["filename"].endswith(".whl"))
    with zipfile.ZipFile(io.BytesIO(get(wheel))) as archive:
        device_map = archive.read("pyvesync/device_map.py").decode()
    return MODEL in device_map


def latest_harness() -> tuple[str, str]:
    """Return the newest test harness and the Home Assistant version it pins.

    Betas are included on purpose: a break shows up before the stable release
    reaches installations with automatic updates.
    """
    data = get_json("https://pypi.org/pypi/pytest-homeassistant-custom-component/json")
    versions = sorted(
        data["releases"], key=lambda v: [int(p) for p in re.findall(r"\d+", v)]
    )
    for version in reversed(versions[-15:]):
        info = get_json(
            f"https://pypi.org/pypi/pytest-homeassistant-custom-component/{version}/json"
        )
        for requirement in info["info"]["requires_dist"] or []:
            match = re.fullmatch(r"homeassistant==([\w.]+)", requirement)
            if match:
                return version, match.group(1)
    raise RuntimeError("no harness pins a Home Assistant version")


def main() -> None:
    """Collect the findings."""
    pr = get_json("https://api.github.com/repos/webdjoe/pyvesync/pulls/552")
    pr_state = "merged" if pr.get("merged_at") else pr["state"]

    core_version = get_json(
        "https://api.github.com/repos/home-assistant/core/releases/latest"
    )["tag_name"]
    manifest = get_json(
        "https://raw.githubusercontent.com/home-assistant/core/"
        f"{core_version}/homeassistant/components/vesync/manifest.json"
    )
    core_pyvesync = next(
        r.split("==")[1] for r in manifest["requirements"] if r.startswith("pyvesync")
    )

    pypi_latest = get_json("https://pypi.org/pypi/pyvesync/json")["info"]["version"]
    harness, harness_ha = latest_harness()

    findings = {
        "pr_state": pr_state,
        "core_version": core_version,
        "core_pyvesync": core_pyvesync,
        "core_supported": str(pyvesync_supports(core_pyvesync)).lower(),
        "pypi_latest": pypi_latest,
        "pypi_supported": str(pyvesync_supports(pypi_latest)).lower(),
        "harness": harness,
        "harness_ha": harness_ha,
    }
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as output:
        for key, value in findings.items():
            print(f"{key}={value}")
            output.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
