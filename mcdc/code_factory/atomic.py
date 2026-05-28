from numba import njit

@njit()
def atomic_add(array, idx, value):
    array[idx] += value

