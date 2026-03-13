#!/usr/bin/env bash
# aiusage install script
# Usage: bash setup.sh
set -e

echo "🤖 Installing aiusage..."

# Check Python version
python_bin=$(command -v python3 || command -v python)
if [ -z "$python_bin" ]; then
    echo "❌  Python 3.10+ is required. Install it from https://python.org"
    exit 1
fi

version=$("$python_bin" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "   Python $version found at $python_bin"

major=$("$python_bin" -c "import sys; print(sys.version_info.major)")
minor=$("$python_bin" -c "import sys; print(sys.version_info.minor)")
if [ "$major" -lt 3 ] || ([ "$major" -eq 3 ] && [ "$minor" -lt 10 ]); then
    echo "❌  Python 3.10+ required (found $version)"
    exit 1
fi

# Install with pip
echo "   Installing dependencies (click, rich)..."
"$python_bin" -m pip install --quiet click rich

echo "   Installing aiusage..."
"$python_bin" -m pip install --quiet -e "$(dirname "$0")"

echo ""
echo "✅  Done! Try these commands:"
echo ""
echo "   aiusage status          # Live Claude rate limits"
echo "   aiusage daily           # Daily token usage from logs"
echo "   aiusage monthly         # Monthly summary"
echo "   aiusage session         # Per-session breakdown"
echo "   aiusage blocks          # 5-hour billing windows"
echo "   aiusage cost            # Estimated cost at API rates"
echo "   aiusage --help          # Full command reference"
echo ""
echo "   Logs are read from: ~/.claude/projects/"
echo "   Config lives at:    ~/.config/aiusage/config.json"
echo ""
