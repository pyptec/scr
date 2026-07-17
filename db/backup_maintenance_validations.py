import argparse

from db.aoki_maintenance_validation_store import (
    DEFAULT_DB_PATH,
    backup_database,
)


def main():
    parser = argparse.ArgumentParser(
        description="Crea un respaldo consistente de la base auxiliar de mantenimiento."
    )
    parser.add_argument("--database", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--destination")
    args = parser.parse_args()
    result = backup_database(args.database, args.destination)
    print(f"Respaldo creado: {result}")


if __name__ == "__main__":
    main()
