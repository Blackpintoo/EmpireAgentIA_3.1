import logging
import sys

# Configuration du logging
logging.basicConfig(
    filename='run.log',  # Fichier de log
    level=logging.INFO,   # Niveau de log
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def main(symbols):
    logging.info("Démarrage du script avec les symboles: %s", symbols)
    
    try:
        # Votre logique ici
        for symbol in symbols:
            logging.info("Traitement du symbole: %s", symbol)
            # Simulez une opération
            # result = process_symbol(symbol)
            # logging.info("Résultat pour %s: %s", symbol, result)

        logging.info("Traitement terminé avec succès.")
    except Exception as e:
        logging.error("Une erreur s'est produite: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    symbols = sys.argv[1:]  # Récupérer les symboles passés en argument
    if not symbols:
        logging.error("Aucun symbole fourni.")
        sys.exit(1)
    main(symbols)