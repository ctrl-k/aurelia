"""Evaluation script for einsum contraction order optimizer.

Tests correctness and performance across increasingly difficult instances.
"""

from __future__ import annotations

import json
import signal
import string
import time
from contextlib import contextmanager
from typing import Any

import numpy as np

from solution import optimize_einsum

# Evaluation configuration
SEED = 42
INSTANCES_PER_LEVEL = 5

LEVELS = [
    {"name": "Level 1", "tensors": (3, 4), "timeout": 1.0},
    {"name": "Level 2", "tensors": (5, 6), "timeout": 5.0},
    {"name": "Level 3", "tensors": (7, 8), "timeout": 10.0},
    {"name": "Level 4", "tensors": (9, 10), "timeout": 30.0},
    {"name": "Level 5", "tensors": (12, 15), "timeout": 60.0},
]


class TimeoutError(Exception):
    """Raised when evaluation times out."""


@contextmanager
def timeout(seconds: float):
    """Context manager for timeout."""
    def handler(signum, frame):
        raise TimeoutError(f"Timed out after {seconds}s")

    old_handler = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def generate_instance(
    rng: np.random.Generator, num_tensors: int
) -> tuple[str, list[tuple[int, ...]]]:
    """Generate a random einsum instance.

    Creates a connected tensor network where each tensor shares at least
    one index with another tensor.
    """
    # Available index labels
    labels = list(string.ascii_lowercase)

    # Track which indices exist and their dimensions
    index_dims: dict[str, int] = {}
    tensor_indices: list[str] = []

    # First tensor: 2-3 random indices
    num_indices = rng.integers(2, 4)  # 4 is exclusive, so 2-3
    first_indices = "".join(rng.choice(labels, size=num_indices, replace=False))
    tensor_indices.append(first_indices)
    for idx in first_indices:
        index_dims[idx] = int(rng.integers(2, 21))  # 21 exclusive, so 2-20

    # Remaining tensors: share at least one index with existing tensors
    used_indices = set(first_indices)
    available_new = [l for l in labels if l not in used_indices]

    for _ in range(num_tensors - 1):
        num_indices = int(rng.integers(2, 5))  # 2-4

        # Pick 1-2 existing indices to connect with
        num_shared = min(int(rng.integers(1, 3)), len(used_indices), num_indices - 1)
        used_list = sorted(used_indices)
        shared = list(rng.choice(used_list, size=num_shared, replace=False))

        # Pick remaining indices (new or reused)
        num_new = num_indices - num_shared
        new_indices = []
        if num_new > 0 and available_new:
            new_count = min(num_new, len(available_new))
            picked = list(rng.choice(available_new, size=new_count, replace=False))
            for idx in picked:
                index_dims[idx] = int(rng.integers(2, 21))
                available_new.remove(idx)
                new_indices.append(idx)
            num_new -= new_count

        # If we still need more indices, reuse existing ones
        if num_new > 0:
            reusable = [i for i in used_indices if i not in shared]
            if reusable:
                extra_count = min(num_new, len(reusable))
                extra = list(rng.choice(reusable, size=extra_count, replace=False))
                new_indices.extend(extra)

        indices = "".join(shared + new_indices)
        tensor_indices.append(indices)
        used_indices.update(indices)

    # Determine output indices (indices that appear exactly once)
    index_count: dict[str, int] = {}
    for indices in tensor_indices:
        for idx in indices:
            index_count[idx] = index_count.get(idx, 0) + 1

    output_indices = "".join(sorted(idx for idx, count in index_count.items() if count == 1))

    # Build subscripts string
    subscripts = ",".join(tensor_indices)
    if output_indices:
        subscripts += "->" + output_indices

    # Build shapes
    shapes = []
    for indices in tensor_indices:
        shape = tuple(index_dims[idx] for idx in indices)
        shapes.append(shape)

    return subscripts, shapes


def verify_correctness(
    subscripts: str,
    shapes: list[tuple[int, ...]],
    path: list,
    rng: np.random.Generator,
) -> bool:
    """Verify that the path produces correct results.

    Uses small tensor dimensions for fast verification - the contraction
    order correctness is independent of tensor size.
    """
    # Create small shapes for fast verification (all dims = 2)
    small_shapes = [tuple(2 for _ in shape) for shape in shapes]
    tensors = [rng.random(shape) for shape in small_shapes]

    # Compute reference result (let numpy choose the path)
    try:
        expected = np.einsum(subscripts, *tensors, optimize=True)
    except Exception:
        return False

    # Compute result using our path
    try:
        actual = np.einsum(subscripts, *tensors, optimize=path)
    except Exception:
        return False

    # Check if results match
    return np.allclose(expected, actual, rtol=1e-5, atol=1e-8)


def evaluate_instance(
    subscripts: str,
    shapes: list[tuple[int, ...]],
    timeout_s: float,
    rng: np.random.Generator,
) -> dict[str, Any]:
    """Evaluate a single instance.

    Measures two things:
    1. Correctness: Does the path produce the right result? (using small tensors)
    2. Performance: How fast does einsum execute with this path? (using actual sizes)
    """
    result = {
        "subscripts": subscripts,
        "shapes": [list(s) for s in shapes],
        "passed": False,
        "time_s": None,
        "error": None,
    }

    try:
        with timeout(timeout_s):
            # Step 1: Compute the path
            path = optimize_einsum(subscripts, *shapes)

            # Step 2: Verify correctness (fast, using small tensors)
            if not verify_correctness(subscripts, shapes, path, rng):
                result["error"] = "incorrect result"
                return result

            # Step 3: Measure execution time with actual tensor sizes
            tensors = [rng.random(shape) for shape in shapes]

            # Warm up
            _ = np.einsum(subscripts, *tensors, optimize=path)

            # Timed run (average of 3)
            times = []
            for _ in range(3):
                start = time.perf_counter()
                _ = np.einsum(subscripts, *tensors, optimize=path)
                times.append(time.perf_counter() - start)

            result["time_s"] = sum(times) / len(times)
            result["passed"] = True

    except TimeoutError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    return result


def evaluate() -> dict[str, Any]:
    """Run full evaluation."""
    rng = np.random.default_rng(SEED)

    results = {
        "levels_passed": 0,
        "total_levels": len(LEVELS),
        "time_bonus": 0.0,
        "score": 0.0,
        "level_results": [],
    }

    for level_idx, level in enumerate(LEVELS):
        level_result = {
            "name": level["name"],
            "timeout": level["timeout"],
            "instances": [],
            "passed": False,
            "total_time": 0.0,
        }

        all_passed = True
        total_time = 0.0

        # Generate and evaluate instances for this level
        for instance_idx in range(INSTANCES_PER_LEVEL):
            # Seed for this specific instance (reproducible)
            instance_seed = SEED + level_idx * 1000 + instance_idx
            instance_rng = np.random.default_rng(instance_seed)

            num_tensors = int(instance_rng.integers(level["tensors"][0], level["tensors"][1] + 1))
            subscripts, shapes = generate_instance(instance_rng, num_tensors)

            instance_result = evaluate_instance(
                subscripts, shapes, level["timeout"], rng
            )
            level_result["instances"].append(instance_result)

            if instance_result["passed"]:
                total_time += instance_result["time_s"]
            else:
                all_passed = False
                break  # Stop at first failure in level

        level_result["passed"] = all_passed
        level_result["total_time"] = total_time
        results["level_results"].append(level_result)

        if all_passed:
            results["levels_passed"] = level_idx + 1
            # Calculate time bonus for this level
            max_time = level["timeout"] * INSTANCES_PER_LEVEL
            results["time_bonus"] = max(0, (max_time - total_time) / max_time)
        else:
            break  # Stop at first failed level

    # Calculate final score
    results["score"] = results["levels_passed"] + results["time_bonus"]

    return results


def main():
    """Run evaluation and print results."""
    results = evaluate()

    # Print summary
    print(f"\n{'=' * 60}")
    print("EINSUM OPTIMIZER EVALUATION")
    print(f"{'=' * 60}\n")

    for level_result in results["level_results"]:
        status = "✓ PASS" if level_result["passed"] else "✗ FAIL"
        print(f"{level_result['name']}: {status}")

        for i, inst in enumerate(level_result["instances"]):
            if inst["passed"]:
                print(f"  Instance {i + 1}: {inst['time_s']:.4f}s")
            else:
                print(f"  Instance {i + 1}: FAILED - {inst['error']}")

        if level_result["passed"]:
            print(f"  Total time: {level_result['total_time']:.4f}s")
        print()

    print(f"{'=' * 60}")
    print(f"Levels passed: {results['levels_passed']}/{results['total_levels']}")
    print(f"Time bonus: {results['time_bonus']:.4f}")
    print(f"FINAL SCORE: {results['score']:.4f}")
    print(f"{'=' * 60}\n")

    # Output JSON for Aurelia
    output = {
        "score": results["score"],
        "levels_passed": results["levels_passed"],
        "time_bonus": round(results["time_bonus"], 4),
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
