from db.samee100_db import init_db
from db.catalogo_unidades import cargar_unidades_excel

if __name__ == "__main__":
    init_db()
    total = cargar_unidades_excel(
        "db/Unidades.xlsx"
    )

    print(f"Se cargaron {total} unidades")