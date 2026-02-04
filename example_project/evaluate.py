import json
import math
import random
import time
from solution import sqrt

def evaluate():
    random.seed(42)
    test_values = [random.uniform(0, 10000) for _ in range(100)]

    # Accuracy
    errors = [abs(sqrt(v) - math.sqrt(v)) for v in test_values]
    mae = sum(errors) / len(errors)

    # Speed
    start = time.perf_counter()
    for v in test_values:
        sqrt(v)
    elapsed_ms = (time.perf_counter() - start) * 1000

    result = {"accuracy": 1.0 - mae, "speed_ms": elapsed_ms}
    print(json.dumps(result))

if __name__ == "__main__":
    evaluate()
