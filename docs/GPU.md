# GPU Setup Notes

The machine has an NVIDIA GPU, but the current TensorFlow runtime is Windows
native TensorFlow 2.21, which does not use CUDA on native Windows.

Useful checks:

```powershell
nvidia-smi
python scripts/check_gpu.py
```

Recommended paths:

1. **Keep this project on Windows and use PyTorch CUDA for future models.**  
   Use the official PyTorch selector for the current Windows + pip + CUDA
   command: https://pytorch.org/get-started/locally/

2. **Use WSL2 for TensorFlow GPU.**  
   TensorFlow documents that native Windows GPU support stopped after 2.10;
   TensorFlow 2.11+ needs WSL2 or DirectML on Windows:
   https://www.tensorflow.org/install/gpu

3. **Keep Keras inference on CPU for now and move training later.**  
   Jarvis already detects when the ML runtime is CPU-only and reports it.
