import getpass
import re
from pathlib import Path

from sqlalchemy.engine import URL

ENV_FILE = Path(__file__).resolve().parent / "Backend" / ".env"
DATABASE_URL_PATTERN = re.compile(r"^\s*DATABASE_URL\s*=.*$", re.MULTILINE)


def _prompt_value(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def main() -> int:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    contents = "\n".join(lines)
    matches = list(DATABASE_URL_PATTERN.finditer(contents))
    if len(matches) > 1:
        print("Backend/.env contains multiple DATABASE_URL entries; resolve them manually.")
        return 1
    if matches and matches[0].group(0).partition("=")[2].strip():
        if input("Replace the existing DATABASE_URL? [y/N]: ").strip().lower() != "y":
            print("No changes made.")
            return 1

    host = _prompt_value("MySQL host", "127.0.0.1")
    raw_port = _prompt_value("MySQL port", "3306")
    database = _prompt_value("MySQL database", "autobi")
    username = input("MySQL username: ").strip()
    if not username:
        print("A MySQL username is required.")
        return 1
    try:
        port = int(raw_port)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        print("MySQL port must be an integer between 1 and 65535.")
        return 1

    password = getpass.getpass("MySQL password (input hidden): ")
    if not password:
        print("A MySQL password is required.")
        return 1

    url = URL.create(
        "mysql+pymysql",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
    ).render_as_string(hide_password=False)
    entry = f"DATABASE_URL={url}"
    if matches:
        match = matches[0]
        contents = contents[: match.start()] + entry + contents[match.end() :]
        lines = contents.splitlines()
    else:
        lines.append(entry)

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    print("Database URL saved to Backend/.env; credentials were not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
