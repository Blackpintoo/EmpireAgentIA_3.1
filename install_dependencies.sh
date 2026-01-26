#!/bin/bash
# =============================================================================
# Script d'installation des dépendances - Empire Agent IA v3
# =============================================================================
# Ce script installe toutes les dépendances Python nécessaires
# Usage: chmod +x install_dependencies.sh && ./install_dependencies.sh
# =============================================================================

set -e  # Arrêter en cas d'erreur

echo "========================================================================"
echo "  INSTALLATION DES DÉPENDANCES - EMPIRE AGENT IA v3"
echo "========================================================================"
echo ""

# Couleurs pour output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Vérifier si on est sur WSL/Linux
if [[ ! -f /etc/os-release ]]; then
    echo -e "${RED}❌ Ce script est conçu pour Linux/WSL${NC}"
    exit 1
fi

echo -e "${YELLOW}📋 Étape 1/4 : Mise à jour des paquets système${NC}"
sudo apt update -qq

echo -e "${YELLOW}📦 Étape 2/4 : Installation de Python 3 et pip${NC}"
sudo apt install -y python3-pip python3-venv python3-dev

echo -e "${YELLOW}🔧 Étape 3/4 : Installation des dépendances système${NC}"
# Installer dépendances système nécessaires
sudo apt install -y \
    libbz2-dev \
    liblzma-dev \
    libssl-dev \
    libffi-dev \
    build-essential

echo -e "${YELLOW}🐍 Étape 4/4 : Installation des modules Python${NC}"

# Créer environnement virtuel
echo "   → Création environnement virtuel..."
python3 -m venv venv

# Activer environnement virtuel
echo "   → Activation environnement virtuel..."
source venv/bin/activate

# Mettre à jour pip
echo "   → Mise à jour pip..."
pip install --upgrade pip setuptools wheel

# Installer dépendances depuis requirements.txt
echo "   → Installation des modules Python..."
pip install -r requirements.txt

echo ""
echo "========================================================================"
echo -e "${GREEN}✅ INSTALLATION TERMINÉE AVEC SUCCÈS !${NC}"
echo "========================================================================"
echo ""
echo "📋 Modules installés :"
pip list | grep -E "pandas|MetaTrader5|feedparser|requests|telegram|yaml|prometheus|pytz|aiogram|apscheduler|dotenv|optuna|textblob|streamlit|matplotlib" || true

echo ""
echo "🎯 Prochaines étapes :"
echo ""
echo "1. Activer l'environnement virtuel :"
echo "   ${YELLOW}source venv/bin/activate${NC}"
echo ""
echo "2. Tester les API externes :"
echo "   ${YELLOW}python test_all_apis.py${NC}"
echo ""
echo "3. Lancer le système en dry-run :"
echo "   ${YELLOW}python main.py --dry-run${NC}"
echo ""
echo "4. Pour désactiver l'environnement virtuel :"
echo "   ${YELLOW}deactivate${NC}"
echo ""
echo "========================================================================"
echo ""
echo "💡 Note : Pour chaque nouvelle session terminal, vous devrez réactiver"
echo "   l'environnement virtuel avec : ${YELLOW}source venv/bin/activate${NC}"
echo ""
echo "========================================================================"
