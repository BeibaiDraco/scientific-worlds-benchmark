## Sparse fourth-order response prior

Let x_0,...,x_719 be the shared input bits and h_j the auxiliary input at
port 720+j. Define s_i = 2*x_i - 1. For each output j, the fixed response is

`z_j = int((2*h_j - 1) + sum_{S subset {0,...,719}, |S|=4} w_{j,S} * product_{i in S} s_i > 0)`.

The coefficients w_{j,S} are fixed, belong to {-2,-1,0,1,2}, and are mostly zero.
The nonzero terms and their coefficients are unknown. The same response law
applies during research and to all manufactured copies.
