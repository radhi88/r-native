import json
import subprocess


def _run(command):
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": completed.returncode == 0,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "returncode": completed.returncode,
    }


def nvidia_smi_summary():
    result = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if not result["ok"] or not result["stdout"]:
        return {"available": False, "error": result.get("stderr") or result.get("error")}

    fields = [part.strip() for part in result["stdout"].splitlines()[0].split(",")]
    keys = ["name", "memory_total_mb", "memory_used_mb", "gpu_util_pct", "driver"]
    return {"available": True, **dict(zip(keys, fields))}


def tensorflow_summary():
    try:
        import tensorflow as tf

        gpus = tf.config.list_physical_devices("GPU")
        return {
            "available": bool(gpus),
            "version": tf.__version__,
            "gpus": [str(gpu) for gpu in gpus],
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def torch_summary():
    try:
        import importlib

        torch = importlib.import_module("torch")

        return {
            "available": bool(torch.cuda.is_available()),
            "version": torch.__version__,
            "device_count": int(torch.cuda.device_count()) if torch.cuda.is_available() else 0,
            "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def hardware_report():
    nvidia = nvidia_smi_summary()
    tensorflow = tensorflow_summary()
    torch = torch_summary()
    recommendation = "cpu"

    if tensorflow.get("available"):
        recommendation = "tensorflow_gpu"
    elif torch.get("available"):
        recommendation = "torch_cuda"
    elif nvidia.get("available"):
        recommendation = "gpu_detected_but_ml_runtime_cpu"

    return {
        "nvidia": nvidia,
        "tensorflow": tensorflow,
        "torch": torch,
        "recommendation": recommendation,
    }


def print_hardware_report():
    print(json.dumps(hardware_report(), indent=2))
