#!/bin/bash
echo "🚀 Chaturdown — Setup"

# Create virtual environment
if [ ! -d "Chaturdown_Venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv Chaturdown_Venv
fi

# Activate and install dependencies
source Chaturdown_Venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Download Camoufox browser (required for ChaturLogin.py)
echo "📥 Downloading Camoufox browser (required for login)..."
python -m camoufox fetch

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Run ./ChaturLogin.py to log in and generate cookies + user agent"
echo "  2. Edit the configuration section at the top of Chaturdown.py"
echo "  3. Run ./Chaturdown.py (or use tmux/screen for background operation)"
