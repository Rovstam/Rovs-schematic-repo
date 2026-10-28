from collections import Counter
from io import TextIOWrapper
from pathlib import Path
from typing import cast
import argparse
import json
import struct
import sys
import tempfile
import zlib

from ignore_single_router_schematics import HEADER, ROOT, SUPPORTED_VERSION, read_java_utf


OUTPUT_FILE = ROOT / "schematic_blocks.txt"
JSONL_OUTPUT_FILE = ROOT / "schematic_blocks.jsonl"

FIXED_OBJECT_SIZES = {
    0: 0,  # null
    1: 4,  # int
    2: 8,  # long
    3: 4,  # float
    5: 3,  # content: byte type + short id
    7: 8,  # Point2
    9: 3,  # tech node: byte type + short id
    10: 1,  # boolean
    11: 8,  # double
    12: 4,  # building position
    13: 2,  # LAccess
    15: 1,  # legacy unit command
    17: 4,  # unit id
    19: 8,  # Vec2
    20: 1,  # team
    23: 2,  # unit command
}

# type id -> (length format, bytes per element)
ARRAY_OBJECT_SIZES = {
    6: (">h", 4),  # int seq
    8: (">B", 4),  # point2 array
    14: (">i", 1),  # byte array
    16: (">i", 1),  # boolean array
    18: (">h", 8),  # vec2 array
    21: (">h", 4),  # int array
}
STRING_TYPE = 4
OBJECT_ARRAY_TYPE = 22


def _need(data: bytes, offset: int, size: int) -> None:
    if offset + size > len(data):
        raise ValueError("truncated schematic data")


def _unpack(fmt: str, data: bytes, offset: int) -> tuple[int, int]:
    size = struct.calcsize(fmt)
    _need(data, offset, size)
    return struct.unpack_from(fmt, data, offset)[0], offset + size


def _skip_object(data: bytes, offset: int, allow_arrays: bool) -> int:
    # Config values are skipped by length; their contents are not needed for counting.
    _need(data, offset, 1)
    type_id = data[offset]
    offset += 1

    if type_id == STRING_TYPE:
        _need(data, offset, 1)
        exists = data[offset]
        offset += 1
        if exists == 0:
            return offset
        length, offset = _unpack(">H", data, offset)
        _need(data, offset, length)
        return offset + length

    if type_id == OBJECT_ARRAY_TYPE or type_id in ARRAY_OBJECT_SIZES:
        if not allow_arrays:
            raise ValueError("nested arrays are not allowed")
        if type_id == OBJECT_ARRAY_TYPE:
            count, offset = _unpack(">i", data, offset)
            if count < 0:
                raise ValueError("invalid array length")
            for _ in range(count):
                offset = _skip_object(data, offset, False)
            return offset
        length_format, element_size = ARRAY_OBJECT_SIZES[type_id]
        length, offset = _unpack(length_format, data, offset)
        if length < 0:
            raise ValueError("invalid array length")
        _need(data, offset, length * element_size)
        return offset + length * element_size

    if type_id in FIXED_OBJECT_SIZES:
        size = FIXED_OBJECT_SIZES[type_id]
        _need(data, offset, size)
        return offset + size

    raise ValueError(f"unknown config type {type_id}")


def count_blocks(path: Path) -> tuple[str, Counter]:
    raw = path.read_bytes()
    if len(raw) < 5 or raw[:4] != HEADER:
        raise ValueError("not a Mindustry schematic (missing msch header)")
    version = raw[4]
    if version > SUPPORTED_VERSION:
        raise ValueError(f"unsupported schematic version {version}")

    data = zlib.decompress(raw[5:])
    offset = 4  # width and height, two shorts

    _need(data, offset, 1)
    tag_count = data[offset]
    offset += 1
    tags = {}
    for _ in range(tag_count):
        key, offset = read_java_utf(data, offset)
        value, offset = read_java_utf(data, offset)
        tags[key] = value
    schematic_name = tags.get("name", path.stem)

    _need(data, offset, 1)
    block_count = data[offset]
    offset += 1
    names = []
    for _ in range(block_count):
        name, offset = read_java_utf(data, offset)
        names.append(name)

    tile_count, offset = _unpack(">i", data, offset)
    counts = Counter()
    for _ in range(tile_count):
        _need(data, offset, 1)
        index = data[offset]
        offset += 1
        if index >= len(names):
            raise ValueError("block index outside block dictionary")
        _, offset = _unpack(">i", data, offset)  # position
        if version == 0:
            _, offset = _unpack(">i", data, offset)  # legacy int config
        else:
            offset = _skip_object(data, offset, True)
        _need(data, offset, 1)
        offset += 1  # rotation
        counts[names[index]] += 1

    return schematic_name, counts


def format_text_record(path: Path, schematic_name: str, counts: Counter) -> str:
    total = sum(counts.values())
    details = ", ".join(f"{name} x{count}" for name, count in sorted(counts.items()))
    filename = path.relative_to(ROOT).as_posix()
    return f"{schematic_name} [{filename}] | {total} blocks | {details or 'empty'}"


def format_jsonl_record(path: Path, schematic_name: str, counts: Counter) -> str:
    record = {
        "schema_version": 1,
        "name": schematic_name,
        "filename": path.relative_to(ROOT).as_posix(),
        "block_count": sum(counts.values()),
        "blocks": dict(sorted(counts.items())),
    }
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def write_atomic(path: Path, content: str) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            output.write(content)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List the block types and block counts in each schematic."
    )
    parser.add_argument(
        "--format",
        choices=("text", "jsonl"),
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="output path; defaults to schematic_blocks.txt or schematic_blocks.jsonl",
    )
    args = parser.parse_args()
    cast(TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    cast(TextIOWrapper, sys.stderr).reconfigure(encoding="utf-8")

    results = []
    errors = []
    for path in sorted(ROOT.rglob("*.msch"), key=lambda item: str(item).casefold()):
        try:
            results.append((path, count_blocks(path)))
        except (OSError, ValueError, zlib.error) as error:
            errors.append((path, error))

    for path, error in errors:
        print(f"Could not inspect {path.relative_to(ROOT).as_posix()}: {error}", file=sys.stderr)

    if errors:
        print(
            "No catalog was written because one or more schematics could not be read.",
            file=sys.stderr,
        )
        print(
            f"Listed {len(results)} schematic(s); {len(errors)} could not be read.",
            file=sys.stderr,
        )
        return 1

    output_path = args.output
    if output_path is None:
        output_path = JSONL_OUTPUT_FILE if args.format == "jsonl" else OUTPUT_FILE

    formatter = format_jsonl_record if args.format == "jsonl" else format_text_record
    content = "\n".join(
        formatter(path, schematic_name, counts)
        for path, (schematic_name, counts) in results
    ) + "\n"

    try:
        write_atomic(output_path, content)
    except OSError as error:
        print(f"Could not write {output_path}: {error}", file=sys.stderr)
        return 1

    print(content, end="")
    print(f"Saved to {output_path}", file=sys.stderr)
    print(f"Listed {len(results)} schematic(s); 0 could not be read.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
