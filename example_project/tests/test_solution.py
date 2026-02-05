from solution import sqrt


def test_sqrt_perfect_squares():
    assert sqrt(4) == 2.0
    assert sqrt(9) == 3.0
    assert sqrt(16) == 4.0

def test_sqrt_zero():
    assert sqrt(0) == 0.0

def test_sqrt_one():
    assert sqrt(1) == 1.0

def test_sqrt_non_perfect():
    assert abs(sqrt(2) - 1.41421356) < 1e-6
