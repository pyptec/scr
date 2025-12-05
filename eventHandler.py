import util

def medidor_conectado():
    params = {
        "t": util.get__time_utc(),   # Añade la hora en UTC
        "g": 10,                 # Número de identificación o índice
        "v": ['0'],                 # Lista de voltajes leídos
        "u": ['53']                 # Lista de unidades
    }  
    # Contiene los eventos dentro de una lista
    return { "d": [params] }   
'''
def sht20_conectado(mensurados):
    params = {
        "t": util.get__time_utc(),   # Añade la hora en UTC
        "g": 10,                 # Número de identificación o índice
        "v": mensurados,                 # Lista de variables  leídos
        "u": ['1','2']                 # Lista de unidades
    }  
    # Contiene los eventos dentro de una lista
    
    return { "d": [params] }   
'''