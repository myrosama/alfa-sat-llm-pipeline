#!/bin/bash
# ================================================================
# ALFA SAT — GPU Fix for Ollama (run once with sudo)
# ================================================================
# PROBLEM:
#   Ollama defaults to CPU because libnvml.so.1 is missing.
#   libnvml is part of the NVIDIA driver management package.
#
# RUN THIS:
#   chmod +x fix_ollama_gpu.sh
#   sudo ./fix_ollama_gpu.sh
#
# AFTER RUNNING:
#   Restart the terminal and re-run the pipeline.
#   You should see GPU utilization spike in nvidia-smi.
# ================================================================

set -e

echo "🔧 Installing NVIDIA management library..."
apt-get install -y libnvidia-ml-dev 2>/dev/null || \
  apt-get install -y libnvml-dev 2>/dev/null || \
  apt-get install -y nvidia-cuda-toolkit 2>/dev/null

echo "🔧 Verifying libnvml..."
ldconfig
ls /usr/lib/x86_64-linux-gnu/libnvml.so* 2>/dev/null && echo "✅ libnvml found in system libs"

echo "🔧 Creating symlink in Ollama's lib dir..."
NVML_LIB=$(find /usr -name "libnvml.so.1" 2>/dev/null | head -1)
if [ -n "$NVML_LIB" ]; then
    ln -sf "$NVML_LIB" /usr/local/lib/ollama/libnvml.so.1
    echo "✅ Symlink created: $NVML_LIB -> /usr/local/lib/ollama/libnvml.so.1"
fi

echo "🔄 Restarting Ollama..."
pkill -f ollama 2>/dev/null || true
sleep 2
ollama serve &> /tmp/ollama_gpu.log &
sleep 5

echo "🔍 Testing GPU detection..."
nvidia-smi --query-gpu=name,memory.used --format=csv,noheader
grep -i "cuda\|gpu" /tmp/ollama_gpu.log | head -5

echo ""
echo "✅ Done! Now run: python batch_runner_local.py"
echo "   Check GPU usage with: watch -n 1 nvidia-smi"
