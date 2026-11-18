"""Pinned portable Windows Neo4j runtime acquisition, never a machine-wide install."""

import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from factorygraph.io import sha256, write_json

ROOT = Path("data/phase4/runtime")
NEO4J = "neo4j-community-5.26.33"
JAVA = "zulu21.54.109-ca-jre21.0.13.0.3-win_x64"
URLS = {
    f"{NEO4J}-windows.zip": f"https://dist.neo4j.org/{NEO4J}-windows.zip",
    f"{JAVA}.zip": f"https://cdn.azul.com/zulu/bin/{JAVA}.zip",
}


def acquire() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / "downloads.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    records = {}
    for name, url in URLS.items():
        target = ROOT / name
        if not target.exists():
            partial = target.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            partial.replace(target)
        digest = sha256(target)
        if name in previous and previous[name]["sha256"] != digest:
            raise ValueError("Runtime archive changed")
        # Verify against the official publisher digest, not just a self-computed hash.
        if name.endswith("-windows.zip"):
            digest_url = url + ".sha256"
            expected = urllib.request.urlopen(digest_url, timeout=40).read().decode().split()[0]
        else:
            digest_url = (
                "https://api.azul.com/metadata/v1/zulu/packages/"
                "c7f161bd-655a-4753-97e4-e1b34a760f17"
            )
            metadata = json.loads(urllib.request.urlopen(digest_url, timeout=40).read())
            write_json(ROOT / "java_publisher_metadata.json", metadata)
            expected = metadata["sha256_hash"]
        if digest.lower() != expected.lower():
            raise ValueError("Publisher runtime checksum mismatch")
        records[name] = {
            "url": url,
            "sha256": digest,
            "publisher_checksum_url": digest_url,
            "bytes": target.stat().st_size,
        }
        directory = ROOT / (NEO4J if name.endswith("-windows.zip") else JAVA)
        if not directory.exists():
            with zipfile.ZipFile(target) as archive:
                for member in archive.namelist():
                    if not (ROOT / member).resolve().is_relative_to(ROOT.resolve()):
                        raise ValueError("Unsafe archive member")
                archive.extractall(ROOT)
    write_json(manifest_path, records)


def configure() -> Path:
    home = (ROOT / NEO4J).resolve()
    if not home.exists():
        raise ValueError("Acquire the pinned runtime first")
    config = home / "conf/neo4j.conf"
    desired = (
        "\n".join(
            [
                "server.default_listen_address=127.0.0.1",
                "server.default_advertised_address=127.0.0.1",
                "server.bolt.enabled=true",
                "server.bolt.listen_address=127.0.0.1:17687",
                "server.bolt.advertised_address=127.0.0.1:17687",
                "server.http.enabled=false",
                "server.https.enabled=false",
                "server.memory.heap.initial_size=256m",
                "server.memory.heap.max_size=768m",
                "server.memory.pagecache.size=256m",
                "dbms.security.auth_enabled=true",
                "dbms.usage_report.enabled=false",
                "server.windows_service_name=FactoryGraphPhase4",
            ]
        )
        + "\n"
    )
    databases = home / "data/databases"
    if databases.exists() and any(databases.iterdir()) and config.read_text() != desired:
        raise ValueError("Refuse to reconfigure an existing database")
    config.write_text(desired, encoding="utf-8")
    return home


def launch() -> dict:
    home = configure()
    env = os.environ.copy()
    env["JAVA_HOME"] = str((ROOT / JAVA).resolve())
    env["NEO4J_HOME"] = str(home)
    password = env.get("FACTORYGRAPH_NEO4J_PASSWORD")
    if not password:
        raise ValueError("Set FACTORYGRAPH_NEO4J_PASSWORD before runtime startup")
    java = Path(env["JAVA_HOME"]) / "bin/java.exe"
    # Official bootloader CLI, using a direct Java process avoids PowerShell policy/WMI changes.
    boot = [str(java), "-cp", str(home / "lib/*"), "org.neo4j.server.startup.Neo4jCommand"]
    if not (home / "data/dbms/auth.ini").exists() and not (home / "data/databases/system").exists():
        admin = [
            str(java),
            "-cp",
            str(home / "lib/*"),
            "org.neo4j.cli.AdminTool",
            "dbms",
            "set-initial-password",
            password,
        ]
        result = subprocess.run(admin, env=env, cwd=home, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Initial authentication setup failed; inspect local runtime logs")
    logs = Path("artifacts/phase4/research")
    logs.mkdir(parents=True, exist_ok=True)
    with (
        (logs / "server.stdout.log").open("a") as stdout,
        (logs / "server.stderr.log").open("a") as stderr,
    ):
        process = subprocess.Popen(
            [*boot, "console"],
            env=env,
            cwd=home,
            stdout=stdout,
            stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    record = {"pid": process.pid, "home": str(home), "bind": "127.0.0.1:17687"}
    write_json(logs / "server_process.json", record)
    return record


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["acquire", "start"])
    args = parser.parse_args()
    if args.stage == "acquire":
        acquire()
    else:
        print(json.dumps(launch()))
