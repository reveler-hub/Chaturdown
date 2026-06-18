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

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Export your Chaturbate cookies as a Netscape-format .txt file (e.g. via a browser extension)."
echo "  2. Save it as 'Chaturdown_Cookies.txt' in this folder."
echo "  3. Edit the configuration section at the top of Chaturdown.py."
echo "  4. Run ./Chaturdown.py (or use tmux/screen for background operation)."
