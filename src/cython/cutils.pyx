cimport cython
from libcpp.map cimport map
import numpy as np
cimport numpy as np

# cython imports
from uniform_kde import uniform_kde_entropy
from gaussian_kde import kde_entropy

# define data types for kde function
DTYPE_INT = np.int
# define compile time data types
ctypedef np.int_t DTYPE_INT_t


cdef extern from "permutation.hpp":
    # import functions from the C++ header permutation.hpp
    int recurrent_sum(map[int, int] pos_ctr)
    double position_entropy(map[int, int] pos_ctr)


@cython.cdivision(True)
def pos_to_codon(seq, int pos):
    """Retrieves information about the codon a nucleotide position is in.

    Parameters
    ----------
    seq : str
        coding sequence
    pos : int
        0-based position of nucleotide in seq

    Returns
    -------
    seq : str
        actual codon sequence
    codon_pos : int
        0-based position of codon (e.g. 3 is the 4th codon)
    pos_in_codon : int
        0-based position within a codon (e.g. 1 is the second
        position out of three)
    """
    cdef int codon_pos, codon_start, pos_in_codon, seq_len = len(seq)
    if pos < seq_len:
        # valid mutation in coding region
        codon_pos = pos / 3
        codon_start = codon_pos * 3
        pos_in_codon = pos % 3
        return seq[codon_start:codon_start+3], codon_pos, pos_in_codon
    else:
        # by assumption, "positions" of splice sites are greater than the
        # length of the coding region to distinguish splice site mutations
        # from coding region mutations
        return 'Splice_Site', None, None


def calc_pos_info(aa_mut_pos, germ_aa, somatic_aa,
                  kde_bw):
    cdef:
        map[int, int] pos_ctr
        int num_recur = 0
        double pos_ent = 0.0
        int i, num_pos
        DTYPE_INT_t[::1] pos_array
    tmp_pos_list = []
    num_pos = len(aa_mut_pos)
    for i in range(num_pos):
        pos = aa_mut_pos[i]
        # make sure mutation is missense
        if germ_aa[i] and somatic_aa[i] and germ_aa[i] != '*' and \
           somatic_aa[i] != '*' and germ_aa[i] != somatic_aa[i]:
            # should have a position, but if not skip it
            if pos is not None:
                if pos_ctr.count(pos) == 0:
                    pos_ctr[pos] = 0
                pos_ctr[pos] += 1
                tmp_pos_list.append(pos)
    num_recur = recurrent_sum(pos_ctr)
    pos_ent = position_entropy(pos_ctr)
    pos_array = np.sort(np.array(tmp_pos_list, dtype=DTYPE_INT, order='c'))
    kde_ent, used_bandwidth = uniform_kde_entropy(pos_array, kde_bw)
    # kde_ent, used_bandwidth = mymath.kde_entropy(np.array(tmp_pos_list, dtype=DTYPE_INT),
    #                                             bandwidth=kde_bw)
    #kde_ent, used_bandwidth = kde_entropy(np.sort(np.array(tmp_pos_list, dtype=DTYPE_INT, order='c')),
    #                                      bandwidth_param=kde_bw)
    return num_recur, pos_ent, kde_ent, used_bandwidth


def calc_deleterious_info(germ_aa, somatic_aa):
    cdef:
        int i, num_mutations = 0, num_deleterious = 0

    num_mutations = len(somatic_aa)
    if len(germ_aa) != num_mutations:
        raise ValueError('There should be equal number of germline and somatic bases')

    for i in range(num_mutations):
        if germ_aa[i] and somatic_aa[i] and \
           ((germ_aa[i] == '*' or somatic_aa[i] == '*') and \
            germ_aa[i] != somatic_aa[i]) or \
           somatic_aa[i] == 'Splice_Site':
            num_deleterious += 1

    return num_deleterious
