"""Einsum contraction order optimizer.

Baseline implementation using a simple greedy heuristic.
"""

from __future__ import annotations


def optimize_einsum(subscripts: str, *shapes: tuple[int, ...]) -> list:
    """Find an efficient contraction order for einsum.

    Args:
        subscripts: Einsum subscripts string (e.g., "ij,jk,kl->il")
        *shapes: Shape of each input tensor, in order

    Returns:
        Contraction path in numpy format: ['einsum_path', (i, j), ...]
        where each (i, j) pair indicates which tensors to contract.
    """
    # Parse the subscripts
    if "->" in subscripts:
        inputs_str, output_str = subscripts.split("->")
    else:
        inputs_str = subscripts
        output_str = None

    input_subs = inputs_str.split(",")

    if len(input_subs) != len(shapes):
        msg = f"Number of subscripts ({len(input_subs)}) != number of shapes ({len(shapes)})"
        raise ValueError(msg)

    # Build index dimension mapping
    index_dims: dict[str, int] = {}
    for subs, shape in zip(input_subs, shapes):
        for idx, dim in zip(subs, shape):
            if idx in index_dims:
                if index_dims[idx] != dim:
                    msg = f"Inconsistent dimension for index '{idx}': {index_dims[idx]} vs {dim}"
                    raise ValueError(msg)
            else:
                index_dims[idx] = dim

    # Track current tensors: list of (subscripts, shape)
    tensors: list[tuple[str, tuple[int, ...]]] = list(zip(input_subs, shapes))
    path: list[tuple[int, int]] = []

    # Greedy: repeatedly contract the pair with smallest intermediate size
    while len(tensors) > 1:
        best_pair = None
        best_cost = float("inf")

        for i in range(len(tensors)):
            for j in range(i + 1, len(tensors)):
                cost = _contraction_cost(tensors[i], tensors[j], index_dims, output_str)
                if cost < best_cost:
                    best_cost = cost
                    best_pair = (i, j)

        i, j = best_pair
        path.append((i, j))

        # Contract tensors i and j
        new_tensor = _contract(tensors[i], tensors[j], output_str)

        # Remove j first (higher index), then i
        tensors.pop(j)
        tensors.pop(i)
        tensors.append(new_tensor)

    return ["einsum_path"] + path


def _contraction_cost(
    t1: tuple[str, tuple[int, ...]],
    t2: tuple[str, tuple[int, ...]],
    index_dims: dict[str, int],
    output_str: str | None,
) -> int:
    """Estimate cost of contracting two tensors.

    Uses size of resulting intermediate tensor as cost metric.
    """
    subs1, _ = t1
    subs2, _ = t2

    # Indices in the result of this contraction
    all_indices = set(subs1) | set(subs2)

    # Indices that will be summed out (appear in both but not in final output)
    contracted = set(subs1) & set(subs2)

    # Keep indices that appear in output or might be needed later
    if output_str:
        # Keep indices in final output
        result_indices = all_indices & set(output_str)
        # Also keep indices that only appear in one tensor (might connect to others)
        result_indices |= (set(subs1) - set(subs2)) | (set(subs2) - set(subs1))
    else:
        # No explicit output - keep non-contracted indices
        result_indices = all_indices - contracted

    # Calculate size of intermediate tensor
    size = 1
    for idx in result_indices:
        size *= index_dims[idx]

    # Add FLOP cost (multiply-adds for contraction)
    flops = size
    for idx in contracted:
        flops *= index_dims[idx]

    # Weight by both intermediate size and FLOP count
    return size + flops


def _contract(
    t1: tuple[str, tuple[int, ...]],
    t2: tuple[str, tuple[int, ...]],
    output_str: str | None,
) -> tuple[str, tuple[int, ...]]:
    """Compute the result of contracting two tensors.

    Returns the subscripts and shape of the resulting tensor.
    """
    subs1, shape1 = t1
    subs2, shape2 = t2

    # Build dimension map for these tensors
    dims: dict[str, int] = {}
    for idx, dim in zip(subs1, shape1):
        dims[idx] = dim
    for idx, dim in zip(subs2, shape2):
        dims[idx] = dim

    # Result keeps indices from either tensor that:
    # 1. Appear in only one tensor (external), or
    # 2. Appear in the final output
    all_indices = set(subs1) | set(subs2)
    contracted = set(subs1) & set(subs2)

    if output_str:
        # Keep indices in final output plus external indices
        external = (set(subs1) - set(subs2)) | (set(subs2) - set(subs1))
        result_indices = (all_indices & set(output_str)) | external
    else:
        result_indices = all_indices - contracted

    # Maintain a consistent order for result indices
    result_subs = "".join(idx for idx in (subs1 + subs2) if idx in result_indices)
    # Remove duplicates while preserving order
    seen = set()
    unique_subs = ""
    for c in result_subs:
        if c not in seen:
            seen.add(c)
            unique_subs += c
    result_subs = unique_subs

    result_shape = tuple(dims[idx] for idx in result_subs)

    return (result_subs, result_shape)
