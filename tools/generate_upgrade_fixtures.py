#!/usr/bin/env python3
"""Generate sanitized upgrade fixtures from pinned integration constructors.

The generated files contain only deterministic synthetic identities.  Upstream
source is executed from a temporary directory and is never copied into NG.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "fixtures" / "upgrades"
SCHEMA_VERSION = 1
HOST = "SVHOST0001"
ENTRY_ID = "01UPGRADEFIXTURE00000000000000"

SOURCES = {
    "official_2_0_0": {
        "repository": "https://github.com/Jackery-Official/jackery",
        "commit": "af97223ff17fc8f14314cbc6da7213a5eee7004d",
        "version": "2.0.0",
        "kind": "official",
    },
    "community_2_5_0": {
        "repository": "https://github.com/csoscd/ha-solarvault",
        "commit": "77d218f6f531c1b5cd0b2ae5b9f2edfe0c61879c",
        "version": "2.5.0",
        "kind": "community",
    },
    "ng_pre_host_scope": {
        "repository": "https://github.com/fred-head/ha-jackery-solarvault-ng",
        "commit": "ed89e745fd7ceab35a52593122f28969cafd3bba",
        "version": "2.4.0",
        "kind": "community",
    },
}

_CONSTRUCTOR_RUNNER = r'''
import json
from custom_components.jackery import sensor, switch

HOST = "SVHOST0001"
ENTRY = "01UPGRADEFIXTURE00000000000000"

class Coordinator:
    _device_sn = HOST
    _data_cache = {}

    def register_sensor(self, *args):
        pass

    def unregister_sensor(self, *args):
        pass

    def get_plug_item(self, *args):
        return None


def normalized(value):
    if isinstance(value, set):
        return sorted(normalized(item) for item in value)
    if isinstance(value, tuple):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    return value


def record(role, domain, entity):
    return {
        "role": role,
        "domain": domain,
        "unique_id": entity._attr_unique_id,
        "device_info": normalized(entity._attr_device_info),
    }


coordinator = Coordinator()
kind = __KIND__
entities = [record("main_soc", "sensor", sensor.JackerySensor("battery_soc", coordinator, ENTRY))]
if kind == "official":
    main_switch = switch.JackeryMainSwitch("swEps", "EPS Output", coordinator, ENTRY)
else:
    main_switch = switch.JackeryMainSwitch("swEps", coordinator, ENTRY, name="EPS Output")
entities.append(record("main_eps_switch", "switch", main_switch))

plug_sensor = sensor.JackerySubDeviceSensor(
    "PLUG0001", 6, "power", sensor.SUBDEVICE_SENSORS["plug"]["power"],
    coordinator, ENTRY, sensor_group="plug",
)
entities.append(record("plug_power", "sensor", plug_sensor))
entities.append(record("plug_switch", "switch", switch.JackeryPlugSwitch("PLUG0001", 6, coordinator, ENTRY)))

if kind == "official":
    meter = sensor.JackerySubDeviceSensor(
        "METER0001", 2, "power_total_forward",
        sensor.SUBDEVICE_SENSORS["ct"]["power_total_forward"],
        coordinator, ENTRY, sensor_group="ct",
    )
    entities.append(record("meter_power", "sensor", meter))
else:
    meter = sensor.JackerySubDeviceSensor(
        "METER0001", 3, "import_total",
        sensor.SUBDEVICE_SENSORS["ct_3phase"]["import_total"],
        coordinator, ENTRY, data_key="cts", sensor_group="ct_3phase",
    )
    battery = sensor.JackerySubDeviceSensor(
        "BATTERY0001", 1, "charge_energy",
        sensor.SUBDEVICE_SENSORS["expansion_battery"]["charge_energy"],
        coordinator, ENTRY, data_key="expansion_batteries", use_expansion=True,
        sensor_group="expansion_battery",
    )
    collector = sensor.JackerySubDeviceSensor(
        "COLLECTOR0001", 4, "import_power",
        sensor.SUBDEVICE_SENSORS["collector"]["import_power"],
        coordinator, ENTRY, data_key="collectors", sensor_group="collector",
    )
    entities.extend([
        record("meter_power", "sensor", meter),
        record("battery_energy", "sensor", battery),
        record("collector_power", "sensor", collector),
    ])

print(json.dumps(entities, sort_keys=True))
'''

CUSTOMIZATIONS = {
    "main_soc": {
        "entity_id": "sensor.my_solarvault_soc",
        "name": "My SolarVault SOC",
        "icon": "mdi:battery-heart",
        "area": "Energy room",
    },
    "main_eps_switch": {
        "entity_id": "switch.backup_output",
        "name": "Backup output",
        "area": "Energy room",
    },
    "plug_power": {
        "entity_id": "sensor.workshop_plug_power",
        "name": "Workshop plug power",
        "icon": "mdi:gauge",
        "area": "Workshop",
        "disabled_by": "user",
    },
    "plug_switch": {
        "entity_id": "switch.workshop_plug",
        "name": "Workshop plug",
        "area": "Workshop",
    },
    "meter_power": {
        "entity_id": "sensor.grid_meter_power",
        "name": "Grid meter power",
        "area": "Utility room",
    },
    "battery_energy": {
        "entity_id": "sensor.expansion_battery_energy",
        "name": "Expansion battery energy",
        "area": "Energy room",
    },
    "collector_power": {
        "entity_id": "sensor.collector_import_power",
        "name": "Collector import power",
        "area": "Utility room",
    },
}


def _run(command: list[str], *, cwd: Path = ROOT, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=capture)


def _has_commit(repository: Path, commit: str) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repository,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _source_repository(spec: dict[str, str], temporary: Path) -> Path:
    if _has_commit(ROOT, spec["commit"]):
        return ROOT
    checkout = temporary / "repository"
    _run(["git", "clone", "--quiet", "--no-checkout", spec["repository"], str(checkout)])
    if not _has_commit(checkout, spec["commit"]):
        _run(["git", "fetch", "--quiet", "origin", spec["commit"]], cwd=checkout)
    return checkout


def _extract_source(repository: Path, commit: str, target: Path) -> None:
    archive = target / "source.tar"
    _run([
        "git", "archive", "--format=tar", f"--output={archive}", commit,
        "custom_components/jackery",
    ], cwd=repository)
    with tarfile.open(archive) as bundle:
        bundle.extractall(target, filter="data")


def _source_hash(source: Path) -> str:
    digest = hashlib.sha256()
    for relative in (
        "custom_components/jackery/manifest.json",
        "custom_components/jackery/sensor.py",
        "custom_components/jackery/switch.py",
    ):
        digest.update(relative.encode())
        digest.update((source / relative).read_bytes())
    return digest.hexdigest()


def _generate(name: str, spec: dict[str, str]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"jackery-upgrade-{name}-") as raw:
        temporary = Path(raw)
        repository = _source_repository(spec, temporary)
        source = temporary / "source"
        source.mkdir()
        _extract_source(repository, spec["commit"], source)
        manifest = json.loads((source / "custom_components/jackery/manifest.json").read_text())
        if manifest["version"] != spec["version"]:
            raise RuntimeError(f"{name}: expected manifest {spec['version']}, got {manifest['version']}")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(source)
        runner = _CONSTRUCTOR_RUNNER.replace("__KIND__", repr(spec["kind"]))
        completed = subprocess.run(
            [sys.executable, "-c", runner], cwd=source, env=environment,
            check=True, text=True, capture_output=True,
        )
        entities = json.loads(completed.stdout)

        device_keys: dict[tuple[tuple[str, str], ...], str] = {}
        devices: list[dict[str, Any]] = []
        for entity in entities:
            info = entity.pop("device_info")
            identifiers = tuple(tuple(item) for item in info["identifiers"])
            if identifiers not in device_keys:
                key = "main" if entity["role"] == "main_soc" else entity["role"].split("_")[0]
                if key in device_keys.values():
                    key = f"{key}_{len(devices)}"
                device_keys[identifiers] = key
                devices.append({
                    "key": key,
                    "identifiers": [list(item) for item in identifiers],
                    "via_device": info.get("via_device"),
                    "name": info.get("name"),
                    "manufacturer": info.get("manufacturer"),
                    "model": info.get("model"),
                    "serial_number": info.get("serial_number"),
                    "name_by_user": "My SolarVault" if key == "main" else f"My {key}",
                    "area": "Energy room" if key in {"main", "battery"} else "Utility room",
                })
            entity["device_key"] = device_keys[identifiers]
            entity["customization"] = CUSTOMIZATIONS[entity["role"]]

        return {
            "schema_version": SCHEMA_VERSION,
            "provenance": {
                "source_repository": spec["repository"],
                "source_commit": spec["commit"],
                "upstream_manifest_version": spec["version"],
                "home_assistant_version": importlib.metadata.version("homeassistant"),
                "generator": "tools/generate_upgrade_fixtures.py",
                "generation_method": "pinned upstream entity constructors executed in isolation",
                "source_files_sha256": _source_hash(source),
            },
            "config_entry": {
                "entry_id": ENTRY_ID,
                "unique_id": HOST,
                "data": {
                    "device_sn": HOST,
                    "token": "synthetic-upgrade-token",
                    "topic_prefix": "hb",
                },
            },
            "synthetic_identities": {
                "host": HOST,
                "children": ["METER0001", "PLUG0001"] + (
                    [] if spec["kind"] == "official" else ["BATTERY0001", "COLLECTOR0001"]
                ),
            },
            "devices": devices,
            "entities": entities,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="compare generated output with committed fixtures")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    differences = []
    for name, spec in SOURCES.items():
        payload = _generate(name, spec)
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        destination = OUTPUT / f"{name}.json"
        if args.check:
            if not destination.exists() or destination.read_text() != rendered:
                differences.append(str(destination.relative_to(ROOT)))
        else:
            destination.write_text(rendered)
            print(destination.relative_to(ROOT))
    if differences:
        raise SystemExit("upgrade fixtures differ: " + ", ".join(differences))


if __name__ == "__main__":
    main()
