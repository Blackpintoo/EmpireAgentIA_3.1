"""
Script de test pour les 3 API externes (Phase 5)

Teste :
1. Finnhub Economic Calendar
2. Alpha Vantage News Sentiment
3. Fear & Greed Index

Usage :
    python test_all_apis.py

Note : Définir FINNHUB_API_KEY et ALPHA_VANTAGE_API_KEY dans .env
"""

import os
import sys
from pathlib import Path

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent))

# Charger les variables d'environnement depuis .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv non installé, lecture directe du .env")
    # Fallback : charger manuellement le .env
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

from connectors.finnhub_calendar import FinnhubCalendar
from connectors.alpha_vantage_news import AlphaVantageNews
from connectors.fear_greed_index import FearGreedIndex


def print_header(title: str):
    """Affiche un en-tête formaté."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_finnhub():
    """Teste Finnhub Economic Calendar."""
    print_header("TEST 1 : FINNHUB ECONOMIC CALENDAR")

    # Vérifier API key
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        print("❌ FINNHUB_API_KEY non définie dans .env")
        print("   → Inscrivez-vous sur https://finnhub.io/ (gratuit)")
        print("   → Ajoutez la clé dans .env : FINNHUB_API_KEY=votre_cle")
        return False

    try:
        client = FinnhubCalendar(api_key=api_key)

        # Test 1 : Récupérer événements
        print("\n1. Récupération événements économiques...")
        events = client.get_economic_events()
        print(f"   ✅ {len(events)} événements récupérés")

        # Test 2 : Filtrer HIGH impact
        print("\n2. Filtrage événements HIGH impact...")
        high_events = client.filter_high_impact_events(events)
        print(f"   ✅ {len(high_events)} événements HIGH impact")

        if high_events:
            print("\n   📅 Exemples d'événements HIGH impact:")
            for event in high_events[:3]:
                print(f"      - {event.get('event')} ({event.get('country')})")
                print(f"        Date: {event.get('date')} {event.get('time')}")

        # Test 3 : Freeze period
        print("\n3. Vérification freeze period pour EURUSD...")
        is_freeze, event_name = client.is_news_freeze_period("EURUSD")
        if is_freeze:
            print(f"   ⚠️  FREEZE actif: {event_name}")
        else:
            print(f"   ✅ Pas de freeze actuellement")

        # Test 4 : Prochain événement
        print("\n4. Prochain événement HIGH impact...")
        next_event = client.get_next_high_impact_event()
        if next_event:
            print(f"   ✅ {next_event.get('event')} ({next_event.get('country')})")
            print(f"      Date: {next_event.get('date')} {next_event.get('time')}")
        else:
            print("   ℹ️  Aucun événement HIGH dans les 7 prochains jours")

        print("\n✅ FINNHUB : Tous les tests réussis")
        return True

    except Exception as e:
        print(f"\n❌ FINNHUB : Erreur - {e}")
        return False


def test_alpha_vantage():
    """Teste Alpha Vantage News Sentiment."""
    print_header("TEST 2 : ALPHA VANTAGE NEWS SENTIMENT")

    # Vérifier API key
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("❌ ALPHA_VANTAGE_API_KEY non définie dans .env")
        print("   → Inscrivez-vous sur https://www.alphavantage.co/ (gratuit)")
        print("   → Ajoutez la clé dans .env : ALPHA_VANTAGE_API_KEY=votre_cle")
        return False

    try:
        client = AlphaVantageNews(api_key=api_key)

        # Test sur 3 symboles
        test_symbols = ["BTCUSD", "EURUSD", "XAUUSD"]

        print("\nTest sentiment pour 3 symboles...")
        print("⚠️  Attention : Limite 25 appels/jour (cache 30 min actif)\n")

        results = []
        for symbol in test_symbols:
            print(f"   {symbol}:")
            sentiment = client.get_news_sentiment(symbol, use_cache=False)

            if sentiment["error"]:
                print(f"      ❌ Erreur: {sentiment['error']}")
                if "rate_limit" in sentiment["error"]:
                    print(f"      ⚠️  Rate limit atteint (25/jour) - test arrêté")
                    break
            else:
                print(f"      ✅ Score: {sentiment['sentiment_score']:.3f}")
                print(f"      📊 Catégorie: {sentiment['category']}")
                print(f"      📰 Articles: {sentiment['articles_count']}")
                print(f"      🎯 Relevance: {sentiment['relevance_score']:.3f}")
                results.append(True)

        if results:
            print(f"\n✅ ALPHA VANTAGE : {len(results)}/{len(test_symbols)} symboles testés avec succès")
            return True
        else:
            print(f"\n⚠️  ALPHA VANTAGE : Aucun symbole testé (vérifier rate limit)")
            return False

    except Exception as e:
        print(f"\n❌ ALPHA VANTAGE : Erreur - {e}")
        return False


def test_fear_greed():
    """Teste Fear & Greed Index."""
    print_header("TEST 3 : FEAR & GREED INDEX")

    try:
        client = FearGreedIndex()

        # Test 1 : Index actuel
        print("\n1. Récupération de l'index actuel...")
        index_data = client.get_fear_greed_index()

        if index_data["error"]:
            print(f"   ❌ Erreur: {index_data['error']}")
            return False

        print(f"   ✅ Valeur: {index_data['value']}/100")
        print(f"   📊 Catégorie: {index_data['category']}")
        print(f"   📝 Classification: {index_data['value_classification']}")
        print(f"   🕒 Prochaine MAJ: {index_data['time_until_update']}")

        # Test 2 : Signal de trading
        print("\n2. Signal de trading contrarian...")
        signal = client.get_sentiment_signal()
        print(f"   🎯 Signal: {signal}")

        # Test 3 : Catégorisation
        print("\n3. Tests de catégorisation...")
        test_values = [10, 30, 50, 70, 90]
        for val in test_values:
            category = client.categorize_value(val)
            sig = client.get_sentiment_signal(val)
            print(f"   {val:3d} → {category:15s} → {sig}")

        print("\n✅ FEAR & GREED : Tous les tests réussis")
        print("   💡 API gratuite, pas de rate limit (MAJ toutes les 8h)")
        return True

    except Exception as e:
        print(f"\n❌ FEAR & GREED : Erreur - {e}")
        return False


def main():
    """Fonction principale."""
    print("\n" + "=" * 70)
    print("  TEST DES 3 API EXTERNES - EMPIRE AGENT IA v3 (Phase 5)")
    print("=" * 70)
    print("\n📋 APIs testées :")
    print("   1. Finnhub Economic Calendar (GRATUIT - 60 appels/min)")
    print("   2. Alpha Vantage News Sentiment (GRATUIT - 25 appels/jour)")
    print("   3. Fear & Greed Index (GRATUIT - sans limite)")

    # Résultats
    results = {
        "Finnhub": False,
        "AlphaVantage": False,
        "FearGreed": False
    }

    # Test 1 : Finnhub
    results["Finnhub"] = test_finnhub()

    # Test 2 : Alpha Vantage
    results["AlphaVantage"] = test_alpha_vantage()

    # Test 3 : Fear & Greed
    results["FearGreed"] = test_fear_greed()

    # Résumé
    print_header("RÉSUMÉ DES TESTS")

    total_tests = len(results)
    passed_tests = sum(1 for r in results.values() if r)

    for api, status in results.items():
        status_icon = "✅" if status else "❌"
        print(f"   {status_icon} {api}")

    print(f"\n📊 Résultat global : {passed_tests}/{total_tests} API fonctionnelles")

    if passed_tests == total_tests:
        print("\n🎉 TOUS LES TESTS RÉUSSIS !")
        print("   → Les 3 API sont opérationnelles")
        print("   → Les agents news/sentiment/fundamental peuvent être utilisés")
    elif passed_tests > 0:
        print("\n⚠️  TESTS PARTIELLEMENT RÉUSSIS")
        print("   → Certaines API fonctionnent, d'autres nécessitent configuration")
        print("   → Vérifier les API keys dans .env")
    else:
        print("\n❌ AUCUN TEST RÉUSSI")
        print("   → Vérifier la configuration dans .env")
        print("   → Obtenir les API keys (voir .env.example)")

    print("\n" + "=" * 70)
    print("\n💡 Pour obtenir vos API keys :")
    print("   - Finnhub : https://finnhub.io/register")
    print("   - Alpha Vantage : https://www.alphavantage.co/support/#api-key")
    print("   - Fear & Greed : (pas de clé requise)")
    print("\n📝 Ensuite :")
    print("   1. Copier .env.example vers .env")
    print("   2. Ajouter vos clés dans .env")
    print("   3. Relancer : python test_all_apis.py")
    print("\n" + "=" * 70 + "\n")

    return passed_tests == total_tests


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
