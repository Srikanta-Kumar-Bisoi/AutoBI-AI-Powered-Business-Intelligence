import getpass
import re
from pathlib import Path

from sqlalchemy.engine import URL

ENV_FILE = Path(__file__).resolve().parent / ".env"
DATABASE_URL_PATTERN = re.compile(r"^\s*DATABASE_URL\s*=.*$", re.MULTILINE)


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

    username = input("MySQL username: ").strip()
    if not username:
        print("A MySQL username is required.")
        return 1
    password = getpass.getpass("MySQL password (input hidden): ")
    if not password:
        print("A MySQL password is required.")
        return 1

    url = URL.create(
        "mysql+pymysql",
        username=username,
        password=password,
        host="127.0.0.1",
        port=3306,
        database="autobi",
    ).render_as_string(hide_password=False)
    entry = f"DATABASE_URL={url}"
    if matches:
        match = matches[0]
        contents = contents[: match.start()] + entry + contents[match.end() :]
        lines = contents.splitlines()
    else:
        lines.append(entry)

    ENV_FILE.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    print("Database URL saved to Backend/.env; credentials were not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
