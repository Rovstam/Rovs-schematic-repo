from pathlib import Path
import argparse
import struct
import sys
import zlib


ROOT = Path(__file__).resolve().parent
GITIGNORE = ROOT / ".gitignore"
HEADER = b"msch"
SUPPORTED_VERSION = 1


def read_java_utf(data: bytes, offset: int) -> tuple[str, int]:
    if offset + 2 > len(data):
        raise ValueError("incomplete string length")

    length = struct.unpack_from(">H", data, offset)[0]
    offset += 2
    end = offset + length
    if end > len(data):
        raise ValueError("incomplete string data")

    encoded = data[offset:end].replace(b"\xc0\x80", b"\x00")
    value = encoded.decode("utf-8", errors="surrogatepass")
    value = value.encode("utf-16-be", errors="surrogatepass").decode("utf-16-be")
    return value, end


def is_single_router(path: Path) -> bool:
    raw = path.read_bytes()
    if len(raw) < 5 or raw[:4] != HEADER:
        raise ValueError("not a Mindustry schematic (missing msch header)")
    if raw[4] > SUPPORTED_VERSION:
        raise ValueError(f"unsupported schematic version {raw[4]}")

    data = zlib.decompress(raw[5:])
    if len(data) < 5:
        raise ValueError("incomplete schematic metadata")

    width, height = struct.unpack_from(">hh", data)
    offset = 4
    tag_count = data[offset]
    offset += 1
    for _ in range(tag_count):
        _, offset = read_java_utf(data, offset)
        _, offset = read_java_utf(data, offset)

    if offset >= len(data):
        raise ValueError("missing block dictionary")
    block_count = data[offset]
    offset += 1
    blocks = []
    for _ in range(block_count):
        block, offset = read_java_utf(data, offset)
        blocks.append(block)

    if offset + 5 > len(data):
        raise ValueError("incomplete schematic tile data")
    tile_count = struct.unpack_from(">i", data, offset)[0]
    offset += 4
    if tile_count != 1 or width != 1 or height != 1 or blocks != ["router"]:
        return False

    return data[offset] == 0


def ignore_pattern(path: Path) -> str:
    relative_path = path.relative_to(ROOT).as_posix()
    escaped = []
    for part in relative_path.split("/"):
        part = part.replace("\\", "\\\\")
        for character in ("*", "?", "[", "]"):
            part = part.replace(character, "\\" + character)
        if part.startswith(("#", "!")):
            part = "\\" + part
        while part.endswith(" "):
            part = part[:-1] + "\\ "
        escaped.append(part)
    return "/" + "/".join(escaped)


def update_gitignore(patterns: list[str]) -> int:
    original = GITIGNORE.read_bytes() if GITIGNORE.exists() else b""
    try:
        existing_lines = original.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError(f"{GITIGNORE.name} is not valid UTF-8: {error}") from error

    additions = [pattern for pattern in patterns if pattern not in existing_lines]
    if not additions:
        return 0

    newline = b"\r\n" if b"\r\n" in original else b"\n"
    separator = newline if original and not original.endswith((b"\n", b"\r")) else b""
    appended = newline.join(pattern.encode("utf-8") for pattern in additions) + newline
    GITIGNORE.write_bytes(original + separator + appended)
    return len(additions)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ignore schematics that contain exactly one 1x1 router."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list matching schematics without changing .gitignore",
    )
    args = parser.parse_args()

    matches = []
    errors = []
    for path in sorted(ROOT.rglob("*.msch"), key=lambda item: str(item).casefold()):
        try:
            if is_single_router(path):
                matches.append(path)
        except (OSError, ValueError, UnicodeError, zlib.error) as error:
            errors.append((path, error))

    if errors:
        for path, error in errors:
            print(f"Could not inspect {path.relative_to(ROOT)}: {error}", file=sys.stderr)
        print("No .gitignore changes were made because some schematics could not be read.", file=sys.stderr)
        return 1

    if not matches:
        print("No single-router schematics found; .gitignore was not changed.")
        return 0

    patterns = [ignore_pattern(path) for path in matches]
    if args.dry_run:
        for pattern in patterns:
            print(pattern)
        print(f"Dry run: {len(patterns)} matching schematic(s); .gitignore was not changed.")
        return 0

    added = update_gitignore(patterns)
    print(f"Found {len(matches)} single-router schematic(s); added {added} rule(s) to .gitignore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
