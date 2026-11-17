## Public material family and generation prior

Shared ports 0 through 719 form 30 disjoint periodic rectangular
square lattices: 10 of size 4 by 4, 10 of size 4 by 6, 10 of size 4 by 8. Port assignment, row-major lattice coordinates and
independent node polarities sigma_i in {-1,+1} are unknown. Generation uniformly
shuffles all shared port labels, assigns consecutive blocks to the listed shapes
(ascending width), independently chooses each polarity with equal probability,
then uniformly shuffles the material list. Set logical spin r_i=sigma_i*(2*x_i-1).
For each material, with both indices wrapping periodically,

`q_g = sum_(a,b) r_(a,b)*r_(a+1,b)*r_(a,b+1)*r_(a+1,b+1)`.

Handle j is known port 720+j with positive polarity and acts directly on output j.
Every output receives 6 distinct materials; every material reaches
4 distinct outputs. Different materials may have identical
output neighborhoods. Incidence uses this finite process, with no claim of exact uniform graph sampling.
Start with edges (g,(4*g+t)%20) for material g=0,...,29 and t=0,...,3.
Perform exactly 20000 proposals. Each proposal selects a uniformly random ordered
pair of distinct current edges (g,j),(h,k). If g=h, j=k, or either cross edge
(g,k),(h,j) already exists, reject the proposal. Otherwise replace the two edges
by (g,k),(h,j). Finally apply independent uniformly shuffled permutations of the
30 material labels and the 20 output labels. All proposals, including rejections,
count toward 20000. This preserves exactly the specified degrees; no graph is
filtered for controller success. The realized proposal/acceptance counts stay
in the judge metadata, not in the research observations.

After incidence is sampled, connected coefficients alpha are independently and
uniformly sampled from {-2,-1,1,2}. The directly reported output is

`z_j = int((2*x_(720+j)-1) + sum_g alpha_jg*q_g > 0)`.

There is no unknown output transformation. Each field is odd, so no threshold tie
is possible. Material structure and couplings stay fixed across research and all
eight manufactured copies. External inputs vary independently across copies.
Every target has a physically affordable controller when suitable structure is known.

The evaluator executes all qualification frames exactly. Physical-verification CPU
is recorded separately from researcher worker CPU. Public files and any supplied
condition-specific assistance contain all instance information available to you.
