"""Tests for the einsum contraction order optimizer."""

from __future__ import annotations

import numpy as np
import pytest

from solution import optimize_einsum


class TestOptimizeEinsum:
    """Tests for the optimize_einsum function."""

    def test_simple_chain(self):
        """Test a simple chain contraction: ij,jk,kl->il."""
        subscripts = "ij,jk,kl->il"
        shapes = [(10, 20), (20, 30), (30, 40)]

        path = optimize_einsum(subscripts, *shapes)

        # Path should have 'einsum_path' + 2 contractions for 3 tensors
        assert path[0] == "einsum_path"
        assert len(path) == 3  # 'einsum_path' + 2 contractions

        # Verify correctness
        tensors = [np.random.rand(*s) for s in shapes]
        expected = np.einsum(subscripts, *tensors, optimize=True)
        actual = np.einsum(subscripts, *tensors, optimize=path)
        assert np.allclose(expected, actual)

    def test_four_tensors(self):
        """Test with 4 tensors."""
        subscripts = "ij,jk,kl,lm->im"
        shapes = [(5, 10), (10, 15), (15, 20), (20, 25)]

        path = optimize_einsum(subscripts, *shapes)

        # Path should have 'einsum_path' + 3 contractions for 4 tensors
        assert path[0] == "einsum_path"
        assert len(path) == 4  # 'einsum_path' + 3 contractions

        # Verify correctness
        tensors = [np.random.rand(*s) for s in shapes]
        expected = np.einsum(subscripts, *tensors, optimize=True)
        actual = np.einsum(subscripts, *tensors, optimize=path)
        assert np.allclose(expected, actual)

    def test_trace(self):
        """Test a trace operation: ii->."""
        # This is a degenerate case with just one tensor
        subscripts = "ij,ji->"
        shapes = [(10, 20), (20, 10)]

        path = optimize_einsum(subscripts, *shapes)

        assert path[0] == "einsum_path"
        assert len(path) == 2  # 'einsum_path' + 1 contraction

        tensors = [np.random.rand(*s) for s in shapes]
        expected = np.einsum(subscripts, *tensors, optimize=True)
        actual = np.einsum(subscripts, *tensors, optimize=path)
        assert np.allclose(expected, actual)

    def test_outer_product(self):
        """Test outer product: i,j->ij."""
        subscripts = "i,j->ij"
        shapes = [(10,), (20,)]

        path = optimize_einsum(subscripts, *shapes)

        assert path[0] == "einsum_path"
        assert len(path) == 2  # 'einsum_path' + 1 contraction

        tensors = [np.random.rand(*s) for s in shapes]
        expected = np.einsum(subscripts, *tensors, optimize=True)
        actual = np.einsum(subscripts, *tensors, optimize=path)
        assert np.allclose(expected, actual)

    def test_shape_mismatch_raises(self):
        """Test that mismatched shapes raise an error."""
        subscripts = "ij,jk->ik"
        shapes = [(10, 20), (30, 40)]  # j dimension doesn't match

        with pytest.raises(ValueError):
            optimize_einsum(subscripts, *shapes)

    def test_wrong_number_of_shapes(self):
        """Test that wrong number of shapes raises an error."""
        subscripts = "ij,jk->ik"
        shapes = [(10, 20)]  # Only 1 shape for 2 subscripts

        with pytest.raises(ValueError):
            optimize_einsum(subscripts, *shapes)

    def test_complex_network(self):
        """Test a more complex tensor network."""
        subscripts = "ab,bc,cd,da->ac"
        shapes = [(5, 10), (10, 15), (15, 20), (20, 5)]

        path = optimize_einsum(subscripts, *shapes)

        assert path[0] == "einsum_path"
        assert len(path) == 4  # 'einsum_path' + 3 contractions

        tensors = [np.random.rand(*s) for s in shapes]
        expected = np.einsum(subscripts, *tensors, optimize=True)
        actual = np.einsum(subscripts, *tensors, optimize=path)
        assert np.allclose(expected, actual)

    def test_no_output_indices(self):
        """Test contraction to scalar."""
        subscripts = "ij,ji"  # No -> means contract everything
        shapes = [(10, 20), (20, 10)]

        path = optimize_einsum(subscripts, *shapes)

        tensors = [np.random.rand(*s) for s in shapes]
        expected = np.einsum(subscripts, *tensors, optimize=True)
        actual = np.einsum(subscripts, *tensors, optimize=path)
        assert np.allclose(expected, actual)


class TestEvaluateScript:
    """Tests for the evaluation script."""

    def test_generate_instance(self):
        """Test that generated instances are valid."""
        from evaluate import generate_instance

        rng = np.random.default_rng(42)
        subscripts, shapes = generate_instance(rng, 5)

        # Should have 5 tensors
        assert len(shapes) == 5
        assert subscripts.count(",") == 4  # 5 tensors means 4 commas

        # Should be able to compute einsum
        tensors = [np.random.rand(*s) for s in shapes]
        result = np.einsum(subscripts, *tensors, optimize=True)
        assert result is not None

    def test_evaluation_runs(self):
        """Test that evaluation completes without error."""
        from evaluate import evaluate

        results = evaluate()

        assert "score" in results
        assert "levels_passed" in results
        assert results["levels_passed"] >= 0
        assert results["score"] >= 0
