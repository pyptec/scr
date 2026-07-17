import argparse
from pathlib import Path

from db.aoki_maintenance_validation_store import (
    DEFAULT_DB_PATH,
    MaintenanceValidationStore,
)


def main():
    parser = argparse.ArgumentParser(
        description="Provisiona localmente un actor de mantenimiento y muestra el token una vez."
    )
    parser.add_argument("actor_id")
    parser.add_argument("display_name")
    parser.add_argument(
        "role", choices=("MAINTENANCE_VALIDATOR", "MAINTENANCE_ADMIN")
    )
    parser.add_argument("--database", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    store = MaintenanceValidationStore(Path(args.database))
    store.initialize()
    token = store.provision_actor(args.actor_id, args.display_name, args.role)
    print(f"Actor creado: {args.actor_id}")
    print(f"Token (se muestra una sola vez): {token}")


if __name__ == "__main__":
    main()
