#!/bin/bash
# Diagnose the 401 HuggingFace error
# Double-click this file to run it

echo "=== myScriber 401 Diagnosis ==="
echo ""

echo "1. HuggingFace token files:"
echo "   ~/.cache/huggingface/token:"
if [ -f "$HOME/.cache/huggingface/token" ]; then
    echo "   FOUND! Contents: $(cat "$HOME/.cache/huggingface/token" | head -c 20)..."
else
    echo "   (not found - good)"
fi
echo "   ~/.huggingface/token:"
if [ -f "$HOME/.huggingface/token" ]; then
    echo "   FOUND! Contents: $(cat "$HOME/.huggingface/token" | head -c 20)..."
else
    echo "   (not found - good)"
fi
echo ""

echo "2. Environment variables:"
echo "   HF_TOKEN=${HF_TOKEN:-(not set)}"
echo "   HUGGING_FACE_HUB_TOKEN=${HUGGING_FACE_HUB_TOKEN:-(not set)}"
echo "   HF_HUB_DISABLE_IMPLICIT_TOKEN=${HF_HUB_DISABLE_IMPLICIT_TOKEN:-(not set)}"
echo ""

echo "3. .netrc file:"
if [ -f "$HOME/.netrc" ]; then
    echo "   FOUND! HuggingFace entries:"
    grep -i "hugging" "$HOME/.netrc" 2>/dev/null || echo "   (no huggingface entries)"
else
    echo "   (not found - good)"
fi
echo ""

echo "4. Git credential helpers:"
git config --global credential.helper 2>/dev/null || echo "   (none)"
git config --global --get-regexp "credential.*hugging" 2>/dev/null || echo "   (no HF-specific git credentials)"
echo ""

echo "5. Git credentials store:"
if [ -f "$HOME/.git-credentials" ]; then
    echo "   FOUND! HuggingFace entries:"
    grep -i "hugging" "$HOME/.git-credentials" 2>/dev/null || echo "   (no huggingface entries)"
else
    echo "   (not found)"
fi
echo ""

echo "6. macOS Keychain (HuggingFace entries):"
security find-internet-password -s "huggingface.co" 2>/dev/null && echo "   FOUND in keychain!" || echo "   (not found in keychain - good)"
echo ""

echo "7. huggingface_hub version:"
"$HOME/.myscriber/venv/bin/python" -c "import huggingface_hub; print(f'   {huggingface_hub.__version__}')" 2>/dev/null || echo "   (could not check)"
echo ""

echo "8. Installed myscriber.py has env var fix:"
grep -c "HF_HUB_DISABLE_IMPLICIT_TOKEN" "$HOME/.myscriber/app/myscriber.py" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "   (fix is present)"
else
    echo "   WARNING: fix not installed! Run update.command first"
fi
echo ""

echo "9. Testing anonymous download directly:"
HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_TOKEN="" HUGGING_FACE_HUB_TOKEN="" \
"$HOME/.myscriber/venv/bin/python" -c "
import os
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
os.environ.pop('HF_TOKEN', None)
os.environ.pop('HUGGING_FACE_HUB_TOKEN', None)
# Delete token files
from pathlib import Path
for p in [Path.home()/'.cache'/'huggingface'/'token', Path.home()/'.huggingface'/'token']:
    if p.exists():
        p.unlink()
        print(f'   Deleted {p}')
from huggingface_hub import snapshot_download
try:
    path = snapshot_download(repo_id='mlx-community/whisper-base', token=False)
    print(f'   SUCCESS! Model at: {path}')
except Exception as e:
    print(f'   FAILED: {e}')
" 2>&1

echo ""
echo "=== Diagnosis complete ==="
echo ""
read -p "Press Enter to close..."
