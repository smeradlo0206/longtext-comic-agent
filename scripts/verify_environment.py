"""Verify local development prerequisites without calling external APIs."""

from importlib.metadata import version


def main() -> None:
    """Print installed core package versions."""

    for package in ["fastapi", "pydantic", "sqlalchemy"]:
        print(f"{package}={version(package)}")


if __name__ == "__main__":
    main()
