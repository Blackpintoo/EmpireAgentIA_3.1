#!/bin/bash
# =============================================================================
# INSTALLATION RAPIDE - Empire Agent IA v3 (Solution 1 - apt système)
# =============================================================================
# Installation via apt (rapide - packages pré-compilés)
# Usage: chmod +x install_quick.sh && ./install_quick.sh
# =============================================================================

set -e

echo "========================================================================"
echo "  INSTALLATION RAPIDE DES DÉPENDANCES (via apt - 5 minutes)"
echo "========================================================================"
echo ""

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}📦 Étape 1/2 : Installation packages système (apt)${NC}"
echo "   → Installation pandas, requests, pyyaml (pré-compilés, rapide)"
sudo apt update -qq
sudo apt install -y \
    python3-pandas \
    python3-requests \
    python3-yaml \
    python3-dotenv \
    python3-six \
    python3-tz

echo ""
echo -e "${YELLOW}🐍 Étape 2/2 : Installation packages Python manquants (pip)${NC}"
echo "   → Installation feedparser, aiogram, etc. (plus légers)"
python3 -m pip install --break-system-packages \
    feedparser \
    prometheus_client \
    aiogram \
    apscheduler \
    optuna \
    textblob

echo ""
echo "========================================================================"
echo -e "${GREEN}✅ INSTALLATION TERMINÉE AVEC SUCCÈS !${NC}"
echo "========================================================================"
echo ""

echo "📋 Vérification des modules installés :"
python3 -c "import pandas; print('  ✅ pandas:', pandas.__version__)"
python3 -c "import requests; print('  ✅ requests:', requests.__version__)"
python3 -c "import yaml; print('  ✅ pyyaml: OK')"
python3 -c "import dotenv; print('  ✅ python-dotenv: OK')"
python3 -c "import feedparser; print('  ✅ feedparser:', feedparser.__version__)"

echo ""
echo "🎯 Prochaines étapes :"
echo ""
echo "1. Tester les API externes :"
echo "   ${YELLOW}python3 test_all_apis.py${NC}"
echo ""
echo "2. Lancer le système en dry-run :"
echo "   ${YELLOW}python3 main.py --dry-run${NC}"
echo ""
echo "========================================================================"
echo ""
echo "⚠️  NOTE : MetaTrader5 n'est PAS installé (Windows uniquement)"
echo "   → Le bot fonctionnera en mode simulation sans connexion MT5"
echo "   → Pour trading RÉEL, utilisez Windows directement"
echo ""
echo "========================================================================"
