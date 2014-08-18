import numpy as np
import pandas as pd
from scipy import stats


def calculate_sem(wp):
    """Calculates the standard error of the mean for a pd.Panel object.

    **Note:** The pd.Panel.apply method seems to have a bug preventing
    me from using it. So instead I am using the numpy apply function
    for calculating sem.

    Parameters
    ----------
    wp : pd.Panel
        panel that stratifies samples

    Returns
    -------
    tmp_sem : pd.DataFrame
        standard error of the mean calculated along the sample axis
    """
    tmp_sem_matrix = np.apply_along_axis(stats.sem, 0, wp.values)  # hack because pandas apply method has a bug
    tmp_sem = pd.DataFrame(tmp_sem_matrix,
                           columns=wp.minor_axis,
                           index=wp.major_axis)
    return tmp_sem


def calculate_stats(result_dict,
                    metrics=['precision', 'recall', 'ROC AUC', 'PR AUC', 'count']):
    """Computes mean and sem of classification performance metrics.

    Parameters
    ----------
    result_dict : dict
        dictionary with the i'th sample as the key and data frames
        with "oncogene"/"tsg" (row) classification performance metrics
        (columns) as values

    Returns
    -------
    result_df : pd.DataFrame
        Data frame with mean and sem of classification performance
        metrics. (rows: "oncogene"/"tsg", columns: summarized metrics)
    """
    wp = pd.Panel(result_dict)
    tmp_means = wp.mean(axis=0)
    tmp_sem = calculate_sem(wp)
    result_df = pd.merge(tmp_means, tmp_sem,
                         left_index=True, right_index=True,
                         suffixes=(' mean', ' sem'))
    return result_df


def save_simulation_result(mypanel, mypath):
    # make 'oncogenes'/'tsg' as the 'items' axis
    mypan = mypanel.swapaxes('items', 'major')

    # collapse pd.panel into a data frame
    myitems = mypan.items
    num_items = len(myitems)
    mydf = mypan[myitems[0]]
    if num_items > 1:
        for i in range(1, num_items):
            mydf = pd.merge(mydf, mypan[myitems[i]],
                            left_on='Gene', right_on='Gene')

    # save data frame to specified paths
    mydf.to_csv(mypath, sep='\t')


def rank_genes(p1, p2,
               fdr1, fdr2,
               thresh=.1,
               na_fill=1.):
    """Rank the p-values of statistically significant genes in either list.

    The thresh variable is the FDR threshold for statistically significant in either
    list. The union of statistically significant genes in both lists is taken.
    This union of genes is then ranked in both lists by p-value.

    Parameters
    ----------
    p1 : pd.Series
        P-values of first test
    p2 : pd.Series
        P-values of second test
    fdr1 : pd.Series
        q-values of first test
    fdr2 : pd.Series
        q-values of second test
    thresh : float
        FDR threshold for statistical significance
    na_fill : float
        value to fill missing p-values (NA's)

    Returns
    -------
    top_rank1 : pd.Series
        gene ranks for first test
    top_rank2 : pd.Series
        gene ranks for second test
    """
    all_ixs = list(set(fdr1[fdr1<thresh].index) | set(fdr1[fdr2<thresh].index))
    top_s1 = p1[all_ixs]
    top_s2 = p2[all_ixs]
    top_rank1 = top_s1.fillna(na_fill).rank()
    top_rank2 = top_s2.fillna(na_fill).rank()
    top_rank2 = top_rank2[top_rank1.index]  # match ordering of index
    return top_rank1, top_rank2


def jaccard_index(fdr1, fdr2,
                  thresh=.1):
    """Calculates the Jaccard Index for statistically significant genes.

    The thresh parameter determines statistical significance for each list.
    It represents the FDR threshold.

    Parameters
    ----------
    fdr1 : pd.Series
        q-values for first test, index should be gene names
    fdr2 : pd.Series
        q-values for second test, index should be gene names
    thresh : float
        FDR threshold for statistical signficance

    Returns
    -------
    jaccard_sim : float
        Jaccard index measuring simularity of statistically significant
        genes in both tests
    """
    s1_genes = set(fdr1[fdr2<thresh].index)
    s2_genes = set(fdr1[fdr2<thresh].index)
    num_intersect = len(s1_genes & s2_genes)
    num_union = len(s1_genes | s2_genes)
    jaccard_sim = num_intersect / float(num_union)
    return jaccard_sim
