import pandas as pd
from pathlib import Path

from db.samee100_db import get_conn


def cargar_unidades_excel(
        archivo_excel="db/Unidades.xlsx",
        hoja=0):
    """
    Carga las unidades desde Excel hacia SQLite.

    Columnas esperadas:
        UnitId
        Name
        Simbol
    """

    archivo = Path(archivo_excel)

    if not archivo.exists():
        raise FileNotFoundError(
            f"No existe el archivo: {archivo}"
        )

    df = pd.read_excel(
        archivo,
        sheet_name=hoja
    )

    columnas = [c.strip() for c in df.columns]
    df.columns = columnas

    requeridas = [
        "UnitId",
        "Name",
        "Simbol"
    ]

    for col in requeridas:
        if col not in df.columns:
            raise ValueError(
                f"No existe la columna {col}"
            )

    conn = get_conn()
    cur = conn.cursor()

    total = 0

    for _, row in df.iterrows():

        try:
            unit_id = int(row["UnitId"])
        except Exception:
            continue

        nombre = str(row["Name"]).strip()

        simbolo = ""

        if not pd.isna(row["Simbol"]):
            simbolo = str(row["Simbol"]).strip()

        cur.execute("""
        INSERT OR REPLACE INTO unidades (
            unit_id,
            name,
            simbol
        )
        VALUES (?, ?, ?)
        """, (
            unit_id,
            nombre,
            simbolo
        ))

        total += 1

    conn.commit()
    conn.close()

    print(
        f"[UNIDADES] {total} unidades cargadas"
    )

    return total