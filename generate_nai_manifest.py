#!/usr/bin/env python3
"""Write the shared NAI app manifest and taxonomy files."""

from __future__ import annotations

import json

from nai_shared import NAI_ISSUES, OUTPUT_ROOT, validate_installed_manifest


def main() -> int:
    specs = validate_installed_manifest()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT_ROOT / "app_manifest.json"
    taxonomy_path = OUTPUT_ROOT / "nai_taxonomy.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "app_name": spec.app_name,
                    "package_name": spec.package_name,
                    "safe_name": spec.safe_name,
                    "category": spec.category,
                    "login_expectation": spec.login_expectation,
                    "targets": spec.targets,
                }
                for spec in specs
            ],
            indent=2,
        )
        + "\n"
    )
    taxonomy_path.write_text(json.dumps(NAI_ISSUES, indent=2) + "\n")
    print(f"Wrote {manifest_path}")
    print(f"Wrote {taxonomy_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
