from scrapers.base_scraper import BaseScraper

productos = [
    'Jamón Cocido Extra', 'Pechuga de Pavo Finas Lonchas', 'Chorizo Ibérico 90g',
    'Fuet Espetec', 'Mortadela con Aceitunas', 'Salchichas Frankfurt',
    'Paté Ibérico', 'Snacks Para Picar De Chorizo', 'Tortilla De Patata',
    'Jamón Serrano Gran Reserva', 'Paleta de Cebo Ibérico', 'Salchichón Nobleza Extra',
    'Lomo Curado 90g', 'Fiambre York Sandwich', 'Pechuga De Pollo Asada',
    'Paté De Cerdo', 'Tapas Chorizo', 'Mini Fuet Alto en Proteína',
]
for p in productos:
    cat = BaseScraper._inferir_categoria_por_nombre(p)
    print(f'{str(cat):30} <- {p}')