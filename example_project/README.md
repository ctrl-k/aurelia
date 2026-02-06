# Einsum Contraction Order Optimizer

## Problem Statement

Given an einsum expression and tensor shapes, find an efficient contraction order that minimizes total computation time.

Einstein summation (`numpy.einsum`) contracts multiple tensors according to index subscripts. The order in which pairwise contractions are performed dramatically affects performance — the difference between optimal and naive ordering can be exponential.

**Example:**
```python
# Expression: "ij,jk,kl->il" with shapes (100,50), (50,80), (80,100)
# Naive (left-to-right): contract ij,jk first → 100*50*80 = 400K ops, then result with kl
# Better: contract jk,kl first → 50*80*100 = 400K ops, but smaller intermediate
```

## Interface

```python
def optimize_einsum(subscripts: str, *shapes: tuple[int, ...]) -> list:
    """Find an efficient contraction order for einsum.

    Args:
        subscripts: Einsum subscripts string (e.g., "ij,jk,kl->il")
        *shapes: Shape of each input tensor, in order

    Returns:
        Contraction path in numpy.einsum format: ['einsum_path', (i, j), ...]
        Each (i, j) pair indicates which tensors to contract at each step.
        Indices refer to the current list of remaining tensors (0-indexed),
        which shrinks after each contraction.

    Example:
        >>> optimize_einsum("ij,jk,kl->il", (10,20), (20,30), (30,40))
        ['einsum_path', (1, 2), (0, 1)]  # Contract 1&2 first, then with 0
    """
```

## Evaluation Criteria

1. **Correctness (required)**: The contraction path must produce the correct result when used with `numpy.einsum_path`.

2. **Performance (scored)**: Solutions are tested on increasingly difficult instances:
   - Level 1: 3-4 tensors (warmup)
   - Level 2: 5-6 tensors
   - Level 3: 7-8 tensors
   - Level 4: 9-10 tensors
   - Level 5: 12-15 tensors (stress test)

   Each level has 5 random instances (seeded for reproducibility). A level is passed only if all instances complete within the timeout and produce correct results.

3. **Scoring**: `score = levels_passed + time_bonus`
   - `time_bonus` = fraction of time remaining on highest passed level

## Constraints

- Input tensors have 2-4 indices each
- Dimension sizes range from 2 to 100
- No external optimization libraries (e.g., opt_einsum) allowed
- Solution must be pure Python + NumPy only

## Hints

- The naive approach (left-to-right) is O(n) but produces poor orderings
- Greedy approaches (minimize immediate cost) work well in practice
- Dynamic programming finds optimal solutions but is O(3^n)
- Consider the size of intermediate tensors, not just FLOP count
