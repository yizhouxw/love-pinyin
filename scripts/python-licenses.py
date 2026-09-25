"""Record installed distribution metadata; preserve upstream license files separately."""

import json
import tomllib
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

lock = tomllib.loads(Path("uv.lock").read_text())
packages = []
for package in lock["package"]:
    if package["name"] == "love-pinyin-server":
        continue
    try:
        dist = distribution(package["name"])
    except PackageNotFoundError:
        packages.append({"name": package["name"], "status": "not-installed-on-this-platform"})
        continue
    meta = dist.metadata
    packages.append(
        {
            "name": meta["Name"],
            "version": meta["Version"],
            "licenseExpression": meta.get("License-Expression"),
            "licenseMetadataFirstLine": (meta.get("License") or "").splitlines()[:1],
            "licenseClassifiers": [
                c for c in meta.get_all("Classifier", []) if c.startswith("License ::")
            ],
            "licenseFiles": meta.get_all("License-File", []),
        }
    )

output = {
    "scope": ("macOS arm64 packages including assessment-poc; metadata is not legal clearance"),
    "packages": packages,
}
Path("docs/engineering/python-dependency-inventory.json").write_text(
    json.dumps(output, ensure_ascii=False, indent=2) + "\n"
)
print(f"Recorded {len(packages)} Python distributions from uv.lock")
