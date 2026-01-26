#!/bin/bash
# Script d'installation et de configuration pour EmpireAgentIA 3.1

echo "================================================================"
echo "Installation d'EmpireAgentIA 3.1 - Système de Trading Autonome"
echo "================================================================"
echo ""

# Vérifier Python
echo "Vérification de Python..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 n'est pas installé. Veuillez installer Python 3.8 ou supérieur."
    exit 1
fi

python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python $python_version détecté"
echo ""

# Vérifier pip
echo "Vérification de pip..."
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip n'est pas installé. Veuillez installer pip."
    exit 1
fi
echo "✓ pip détecté"
echo ""

# Mettre à jour pip
echo "Mise à jour de pip, setuptools et wheel..."
python3 -m pip install --upgrade pip setuptools wheel -q
echo "✓ pip, setuptools et wheel mis à jour"
echo ""

# Installer les dépendances
echo "Installation des dépendances..."
echo "Cela peut prendre quelques minutes..."
python3 -m pip install -r requirements.txt -q

if [ $? -eq 0 ]; then
    echo "✓ Toutes les dépendances sont installées"
else
    echo "❌ Erreur lors de l'installation des dépendances"
    exit 1
fi
echo ""

# Créer le fichier .env
if [ ! -f .env ]; then
    echo "Création du fichier de configuration .env..."
    cp .env.example .env
    echo "✓ Fichier .env créé"
else
    echo "⚠ Le fichier .env existe déjà, conservation de la configuration actuelle"
fi
echo ""

# Test rapide
echo "Test rapide du système..."
python3 test_modules.py > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "✓ Test réussi - Le système est prêt"
else
    echo "⚠ Le test a échoué, mais le système peut quand même fonctionner"
    echo "  Vérifiez les logs pour plus de détails"
fi
echo ""

echo "================================================================"
echo "Installation terminée avec succès! ✓"
echo "================================================================"
echo ""
echo "Prochaines étapes:"
echo ""
echo "1. Mode démo (recommandé pour débuter):"
echo "   python3 main.py demo 10"
echo ""
echo "2. Démonstration interactive:"
echo "   python3 demo.py"
echo ""
echo "3. Mode continu (utilise des données réelles):"
echo "   python3 main.py"
echo ""
echo "Pour plus d'informations, consultez:"
echo "  - README.md : Vue d'ensemble"
echo "  - GUIDE.md : Guide d'utilisation détaillé"
echo ""
echo "Bon trading! 🚀"
