#!/bin/bash

BASE_DIR="/home/pi/SAMEE100/scr"
DB_PATH="$BASE_DIR/data/samee100.db"
BACKUP_DIR="$BASE_DIR/backup"
FECHA=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/samee100_$FECHA.db"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: No existe la base de datos: $DB_PATH"
    exit 1
fi

sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

if [ $? -ne 0 ]; then
    echo "ERROR: Falló el backup de SQLite"
    exit 1
fi

echo "Backup creado: $BACKUP_FILE"

# Mantener solamente los últimos 5 backups
ls -1t "$BACKUP_DIR"/samee100_*.db 2>/dev/null | tail -n +6 | xargs -r rm -f

echo "Backups actuales:"
ls -lh "$BACKUP_DIR"/samee100_*.db 2>/dev/null