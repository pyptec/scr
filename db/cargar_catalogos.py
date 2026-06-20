from catalogo_unidades import cargar_unidades_excel

if __name__ == "__main__":
    total = cargar_unidades_excel(
        "Unidades.xlsx"
    )

    print(f"Se cargaron {total} unidades")