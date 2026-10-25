from pathlib import Path
import struct
import sys
import zlib


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "schematic-names.txt"
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


def in_game_name(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) < 5 or raw[:4] != HEADER:
        raise ValueError("not a Mindustry schematic (missing msch header)")
    if raw[4] > SUPPORTED_VERSION:
        raise ValueError(f"unsupported schematic version {raw[4]}")

    data = zlib.decompress(raw[5:])
    if len(data) < 5:
        raise ValueError("incomplete schematic metadata")

    offset = 4  # Skip width and height.
    tag_count = data[offset]
    offset += 1
    tags = {}
    for _ in range(tag_count):
        key, offset = read_java_utf(data, offset)
        value, offset = read_java_utf(data, offset)
        tags[key] = value

    return tags.get("name", path.stem)


def main() -> int:
    files = sorted(ROOT.rglob("*.msch"), key=lambda path: str(path).casefold())
    lines = ["Ingame name = Explorer name"]
    errors = 0

    for path in files:
        try:
            name = in_game_name(path)
            name = name.replace("\r", " ").replace("\n", " ")
            lines.append(f"{name} = {path.name}")
        except (OSError, ValueError, UnicodeError, zlib.error) as error:
            errors += 1
            print(f"Could not read {path.name}: {error}", file=sys.stderr)

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(files) - errors} schematic names to {OUTPUT.name}.")
    if errors:
        print(f"Skipped {errors} unreadable schematic(s); see errors above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
