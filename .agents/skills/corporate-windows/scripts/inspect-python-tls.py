from __future__ import annotations

import argparse
import json
import os
import platform
import ssl
import sys
from pathlib import Path


def path_observation(value: str | None, include_paths: bool) -> dict[str, object]:
    if not value:
        return {"configured": False}
    path = Path(value)
    result: dict[str, object] = {
        "configured": True,
        "exists": path.exists(),
        "ascii": value.isascii(),
        "length": len(value),
    }
    if include_paths:
        result["path"] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect Python TLS configuration without making a network request."
    )
    parser.add_argument(
        "--include-paths",
        action="store_true",
        help="Include certificate path values instead of only safe path properties.",
    )
    args = parser.parse_args()

    try:
        import truststore  # type: ignore[import-not-found]

        truststore_info: dict[str, object] = {
            "available": True,
            "version": getattr(truststore, "__version__", "unknown"),
        }
    except ImportError:
        truststore_info = {"available": False}

    verify_paths = ssl.get_default_verify_paths()
    result = {
        "schema_version": 1,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_ascii": sys.executable.isascii(),
            "executable_length": len(sys.executable),
        },
        "ssl": {
            "openssl_version": ssl.OPENSSL_VERSION,
            "default_verify_paths": {
                "cafile": path_observation(verify_paths.cafile, args.include_paths),
                "capath": path_observation(verify_paths.capath, args.include_paths),
                "openssl_cafile_env_present": bool(
                    os.environ.get(verify_paths.openssl_cafile_env)
                ),
                "openssl_capath_env_present": bool(
                    os.environ.get(verify_paths.openssl_capath_env)
                ),
            },
        },
        "truststore": truststore_info,
        "network_request_performed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
