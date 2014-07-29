#!/usr/bin/env python
# fix problems with pythons terrible import system
import os
import sys
file_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(file_dir, '../src/python'))
sys.path.append(os.path.join(file_dir, '../src/cython'))

# normal imports
import utils
from gene_sequence import GeneSequence
from sequence_context import SequenceContext
import cutils
import argparse
import pysam
import pandas as pd
import numpy as np
from multiprocessing import Pool
import logging
import datetime
import itertools as it
from functools import wraps

logger = logging.getLogger(__name__)  # module logger

def start_logging(log_file='', log_level='INFO'):
    """Start logging information into the log directory.

    If os.devnull is specified as the log_file then the log file will
    not actually be written to a file.
    """
    if not log_file:
        log_file = 'log/log.run.' + str(datetime.datetime.now()).replace(':', '.') + '.txt'

    # logger options
    lvl = logging.DEBUG if log_level.upper() == 'DEBUG' else logging.INFO
    myformat = '%(asctime)s - %(name)s - %(levelname)s \n>>>  %(message)s'

    # create logger
    if not log_file == 'stdout':
        # normal logging to a regular file
        logging.basicConfig(level=lvl,
                            format=myformat,
                            filename=log_file,
                            filemode='w')
    else:
        # logging to stdout
        root = logging.getLogger()
        root.setLevel(lvl)
        stdout_stream = logging.StreamHandler(sys.stdout)
        stdout_stream.setLevel(lvl)
        formatter = logging.Formatter(myformat)
        stdout_stream.setFormatter(formatter)
        root.addHandler(stdout_stream)
        root.propagate = True


def log_error_decorator(f):
    """Writes exception to log file if occured in decorated function.

    This decorator wrapper is needed for multiprocess logging since otherwise
    the python multiprocessing module will obscure the actual line of the error.
    """
    @wraps(f)
    def wrapper(*args, **kwds):
        try:
            result = f(*args, **kwds)
            return result
        except KeyboardInterrupt:
            pass
        except Exception, e:
            logger.exception(e)
            raise
    return wrapper


def keyboard_exit_wrapper(func):
    def wrap(self, timeout=None):
        # Note: the timeout of 1 googol seconds introduces a rather subtle
        # bug for Python scripts intended to run many times the age of the universe.
        return func(self, timeout=timeout if timeout is not None else 1e100)
    return wrap


def deleterious_permutation(context_counts,
                            context_to_mut,
                            seq_context,
                            gene_seq,
                            num_permutations=10000):
    mycontexts = context_counts.index.tolist()
    somatic_base = [base
                    for one_context in mycontexts
                    for base in context_to_mut[one_context]]

    del_count_list = []
    tmp_contxt_pos = seq_context.random_pos(context_counts.iteritems(),
                                            num_permutations)
    tmp_mut_pos = np.hstack(pos_array for base, pos_array in tmp_contxt_pos)
    for row in tmp_mut_pos:
        # get info about mutations
        tmp_mut_info = utils.get_aa_mut_info(row,
                                             somatic_base,
                                             gene_seq)

        # calc deleterious mutation info
        tmp_del_count = cutils.calc_deleterious_info(tmp_mut_info['Reference AA'],
                                                     tmp_mut_info['Somatic AA'])

        del_count_list.append(tmp_del_count)
    return del_count_list


def position_permutation(context_counts,
                         context_to_mut,
                         seq_context,
                         gene_seq,
                         num_permutations=10000,
                         kde_bandwidth=None):
    mycontexts = context_counts.index.tolist()
    somatic_base = [base
                    for one_context in mycontexts
                    for base in context_to_mut[one_context]]
    num_recur_list, entropy_list, kde_entropy_list, bw_list = [], [], [], []
    tmp_contxt_pos = seq_context.random_pos(context_counts.iteritems(),
                                            num_permutations)
    tmp_mut_pos = np.hstack(pos_array for base, pos_array in tmp_contxt_pos)
    for row in tmp_mut_pos:
        # get info about mutations
        tmp_mut_info = utils.get_aa_mut_info(row,
                                             somatic_base,
                                             gene_seq)

        # calculate position info
        tmp_recur_ct, tmp_entropy, tmp_kde_ent, tmp_bw = cutils.calc_pos_info(tmp_mut_info['Codon Pos'],
                                                                              tmp_mut_info['Reference AA'],
                                                                              tmp_mut_info['Somatic AA'],
                                                                              kde_bandwidth)
        num_recur_list.append(tmp_recur_ct)
        entropy_list.append(tmp_entropy)
        kde_entropy_list.append(tmp_kde_ent)
        bw_list.append(tmp_bw)

    return num_recur_list, entropy_list, kde_entropy_list, bw_list


def read_bed(file_path, filtered_genes):
    # read in entire bed file into a dict with keys as chromsomes
    bed_dict = {}
    for bed_row in utils.bed_generator(file_path):
        if bed_row.gene_name not in filtered_genes:
            bed_dict.setdefault(bed_row.chrom, [])
            bed_dict[bed_row.chrom].append(bed_row)
    return bed_dict


def calc_deleterious_result(mut_info,
                            sc,
                            gs,
                            bed,
                            num_permutations,
                            del_threshold):
    if len(mut_info) > 0:
        mut_info['Coding Position'] = mut_info['Coding Position'].astype(int)
        mut_info['Context'] = mut_info['Coding Position'].apply(lambda x: sc.pos2context[x])

        # group mutations by context
        context_cts = mut_info['Context'].value_counts()
        context_to_mutations = dict((name, group['Tumor_Allele'])
                                    for name, group in mut_info.groupby('Context'))


        # get deleterious info for actual mutations
        aa_mut_info = utils.get_aa_mut_info(mut_info['Coding Position'],
                                            mut_info['Tumor_Allele'].tolist(),
                                            gs)
        num_del = cutils.calc_deleterious_info(aa_mut_info['Reference AA'],
                                               aa_mut_info['Somatic AA'])

        # skip permutation test if number of deleterious mutations is not at
        # least meet some user-specified threshold
        if num_del >= del_threshold:
            # perform permutations
            num_del_list = deleterious_permutation(context_cts,
                                                   context_to_mutations,
                                                   sc,  # sequence context obj
                                                   gs,
                                                   num_permutations)  # gene sequence obj

            # calculate p-value
            del_num_nulls = sum([1 for d in num_del_list
                                if d >= num_del])
            del_p_value = del_num_nulls / float(num_permutations)
        else:
            del_p_value = None
    else:
        num_del = 0
        del_p_value = None

    result = [bed.gene_name, num_del, del_p_value]
    return result


def calc_position_result(mut_info,
                         sc,
                         gs,
                         bed,
                         num_permutations):
    if len(mut_info) > 0:
        mut_info['Coding Position'] = mut_info['Coding Position'].astype(int)
        mut_info['Context'] = mut_info['Coding Position'].apply(lambda x: sc.pos2context[x])

        # group mutations by context
        context_cts = mut_info['Context'].value_counts()
        context_to_mutations = dict((name, group['Tumor_Allele'])
                                    for name, group in mut_info.groupby('Context'))

        # perform permutations
        permutation_result = position_permutation(context_cts,
                                                  context_to_mutations,
                                                  sc,  # sequence context obj
                                                  gs,
                                                  num_permutations)  # gene sequence obj
        num_recur_list, pos_entropy_list, kde_entropy_list, bw_list = permutation_result  # unpack results

        # get recurrent info for actual mutations
        aa_mut_info = utils.get_aa_mut_info(mut_info['Coding Position'],
                                            mut_info['Tumor_Allele'].tolist(),
                                            gs)
        num_recurrent, pos_ent, kde_ent, opt_bw = cutils.calc_pos_info(aa_mut_info['Codon Pos'],
                                                                       aa_mut_info['Reference AA'],
                                                                       aa_mut_info['Somatic AA'],
                                                                       None)

        # calculate permutation p-value
        recur_num_nulls = sum([1 for null_recur in num_recur_list
                               if null_recur >= num_recurrent])
        entropy_num_nulls = sum([1 for null_ent in pos_entropy_list
                                 if null_ent <= pos_ent])
        kde_entropy_num_nulls = sum([1 for null_ent in kde_entropy_list
                                     if null_ent <= kde_ent])
        kde_bw_num_nulls = sum([1 for null_bw in bw_list
                                if null_bw <= opt_bw])
        recur_p_value = recur_num_nulls / float(num_permutations)
        ent_p_value = entropy_num_nulls / float(num_permutations)
        kde_ent_p_value = kde_entropy_num_nulls / float(num_permutations)
        kde_bw_p_value = kde_bw_num_nulls / float(num_permutations)
    else:
        num_recurrent = 0
        pos_ent = 0
        kde_ent = 0
        opt_bw = 0
        recur_p_value = 1.0
        ent_p_value = 1.0
        kde_ent_p_value = 1.0
        kde_bw_p_value = 1.0
    result = [bed.gene_name, num_recurrent, pos_ent, kde_ent, opt_bw,
              recur_p_value, ent_p_value, kde_ent_p_value, kde_bw_p_value]
    return result


@log_error_decorator
def singleprocess_permutation(info):
    bed_list, mut_df, opts = info
    current_chrom = bed_list[0].chrom
    logger.info('Working on chromosome: {0} . . .'.format(current_chrom))
    num_permutations = opts['num_permutations']
    gene_fa = pysam.Fastafile(opts['input'])
    gs = GeneSequence(gene_fa, nuc_context=opts['context'])

    result = []
    for bed in bed_list:
        # prepare info for running permutation test
        gene_mut = mut_df[mut_df['Gene']==bed.gene_name]
        cols = ['Chromosome', 'Start_Position', 'Reference_Allele', 'Tumor_Allele']
        mut_info = gene_mut[cols]
        gs.set_gene(bed)
        pos_list = []
        for ix, row in mut_info.iterrows():
            coding_pos = bed.query_position(row['Chromosome'], row['Start_Position'])
            pos_list.append(coding_pos)
        mut_info['Coding Position'] = pos_list
        mut_info = mut_info.dropna()
        mut_info['Coding Position'] = mut_info['Coding Position'].astype(int)
        gs.add_germline_variants(mut_info['Reference_Allele'].tolist(),
                                 mut_info['Coding Position'].tolist())
        sc = SequenceContext(gs)

        # calculate results of permutation test
        if opts['kind'] == 'oncogene':
            # calculate position based permutation results
            tmp_result = calc_position_result(mut_info, sc, gs, bed, num_permutations)
            result.append(tmp_result)
        else:
            # calculate results for deleterious mutation permutation test
            tmp_result = calc_deleterious_result(mut_info, sc, gs,
                                                 bed, num_permutations,
                                                 opts['deleterious'])
            result.append(tmp_result)

    gene_fa.close()
    logger.info('Finished working on chromosome: {0}.'.format(current_chrom))
    return result


def multiprocess_permutation(bed_dict, mut_df, opts):
    chroms = sorted(bed_dict.keys())
    num_processes = opts['processes']
    result_list = []
    for i in range(0, len(chroms), num_processes):
        pool = Pool(processes=num_processes)
        tmp_num_proc = len(chroms) - i if i + num_processes > len(chroms) else num_processes
        info_repeat = ((bed_dict[chroms[tmp_ix]], mut_df, opts)
                        for tmp_ix in range(i, i+tmp_num_proc))
        process_results = pool.imap(singleprocess_permutation, info_repeat)
        process_results.next = keyboard_exit_wrapper(process_results.next)
        try:
            for chrom_result in process_results:
                result_list += chrom_result
        except KeyboardInterrupt:
            pool.close()
            pool.join
            logger.info('Exited by user. ctrl-c')
            sys.exit(0)
        pool.close()
        pool.join()

    return result_list


def _fix_mutation_df(mutation_df):
    allowed_types = ['Missense_Mutation', 'Silent', 'Nonsense_Mutation']
    mutation_df = mutation_df[mutation_df.Variant_Classification.isin(allowed_types)]  # only keep SNV
    valid_nuc_flag = mutation_df['Reference_Allele'].apply(utils.is_valid_nuc) & mutation_df['Tumor_Allele'].apply(utils.is_valid_nuc)
    mutation_df = mutation_df[valid_nuc_flag]  # filter bad lines
    mutation_df['Start_Position'] = mutation_df['Start_Position'] - 1
    mutation_df = mutation_df[mutation_df['Tumor_Allele'].apply(lambda x: len(x)==1)]
    mutation_df = mutation_df[mutation_df['Reference_Allele'].apply(lambda x: len(x)==1)]
    return mutation_df


def _get_high_tsg_score(mutation_df, tsg_score_thresh):
    mutation_df['indicator'] = 1
    table = pd.pivot_table(mutation_df,
                           values='indicator',
                           cols='Variant_Classification',
                           rows='Gene',
                           aggfunc=np.sum)
    mut_type_frac = table.div(table.sum(axis=1).astype(float), axis=0).fillna(0.0)
    for c in ['Nonsense_Mutation', 'Frame_Shift_Indel', 'Splice_Site', 'Nonstop_Mutation']:
        if c not in mut_type_frac.columns:
            mut_type_frac[c] = 0.0  # make sure columns are defined
    tsg_score = mut_type_frac['Nonsense_Mutation'] + mut_type_frac['Frame_Shift_Indel'] + \
                mut_type_frac['Splice_Site'] + mut_type_frac['Nonstop_Mutation']
    non_tested_genes = set(tsg_score[tsg_score>=tsg_score_thresh].index.tolist())
    return non_tested_genes


def parse_arguments():
    # make a parser
    info = 'Performs a permutation test on the oncogene and TSG score'
    parser = argparse.ArgumentParser(description=info)

    # logging arguments
    parser.add_argument('-ll', '--log-level',
                        type=str,
                        action='store',
                        default='',
                        help='Write a log file (--log-level=DEBUG for debug mode, '
                        '--log-level=INFO for info mode)')
    parser.add_argument('-l', '--log',
                        type=str,
                        action='store',
                        default='',
                        help='Path to log file. (accepts "stdout")')

    # program arguments
    help_str = 'gene FASTA file from extract_gene_seq.py script'
    parser.add_argument('-i', '--input',
                        type=str, required=True,
                        help=help_str)
    help_str = 'DNA mutations file'
    parser.add_argument('-m', '--mutations',
                        type=str, required=True,
                        help=help_str)
    help_str = 'BED file annotation of genes'
    parser.add_argument('-b', '--bed',
                        type=str, required=True,
                        help=help_str)
    help_str = 'Number of processes to use (more==Faster, default: 1).'
    parser.add_argument('-p', '--processes',
                        type=int, default=1,
                        help=help_str)
    help_str = 'Number of permutations for null model'
    parser.add_argument('-n', '--num-permutations',
                        type=int, default=10000,
                        help=help_str)
    help_str = ('Kind of permutation test to perform ("oncogene" or "tsg"). "position-based" permutation '
                'test is intended to find oncogenes using position based statistics. '
                'The "deleterious" permutation test is intended to find tumor '
                'suppressor genes. (Default: oncogene)')
    parser.add_argument('-k', '--kind',
                        type=str, default='oncogene',
                        help=help_str)
    help_str = ('Number of DNA bases to use as context. 0 indicates no context. '
                '1 indicates only use the mutated base.  1.5 indicates using '
                'the base context used in CHASM '
                '(http://wiki.chasmsoftware.org/index.php/CHASM_Overview). '
                '2 indicates using the mutated base and the upstream base. '
                '3 indicates using the mutated base and both the upstream '
                'and downstream bases. (Default: 1.5)')
    parser.add_argument('-c', '--context',
                        type=float, default=1.5,
                        help=help_str)
    help_str = ('Perform recurrent mutation permutation test if gene has '
                'atleast a user specified number of recurrent mutations (default: 2)')
    parser.add_argument('-r', '--recurrent',
                        type=int, default=2,
                        help=help_str)
    help_str = ('Perform tsg permutation test if gene has '
                'atleast a user specified number of deleterious mutations (default: 1)')
    parser.add_argument('-d', '--deleterious',
                        type=int, default=1,
                        help=help_str)
    help_str = ('Maximum TSG score to allow gene to be tested for oncogene '
                'permutation test. (Default: .10)')
    parser.add_argument('-t', '--tsg-score',
                        type=float, default=.10,
                        help=help_str)
    help_str = 'Output of probabilistic 20/20 results'
    parser.add_argument('-o', '--output',
                        type=str, required=True,
                        help=help_str)
    args = parser.parse_args()

    # handle logging
    if args.log_level or args.log:
        if args.log:
            log_file = args.log
        else:
            log_file = ''  # auto-name the log file
    else:
        log_file = os.devnull
    log_level = args.log_level
    start_logging(log_file=log_file,
                  log_level=log_level)  # start logging

    return vars(args)


def main(opts):
    # hack to index the FASTA file
    gene_fa = pysam.Fastafile(opts['input'])
    gene_fa.close()

    # Get Mutations
    mut_df = pd.read_csv(opts['mutations'], sep='\t')

    if opts['kind'] == 'oncogene':
        # find genes with tsg score above threshold to filter out for oncogene
        # permutation test
        non_tested_genes = _get_high_tsg_score(mut_df, opts['tsg_score'])
    else:
        # don't filter out genes for tsg permutation test
        non_tested_genes = []

    # select valid single nucleotide variants only
    mut_df = _fix_mutation_df(mut_df)

    # perform permutation test
    bed_dict = read_bed(opts['bed'], non_tested_genes)
    permutation_result = multiprocess_permutation(bed_dict, mut_df, opts)

    if opts['kind'] == 'oncogene':
        permutation_df = pd.DataFrame(sorted(permutation_result, key=lambda x: x[5]),
                                      columns=['gene', 'num recurrent', 'position entropy',
                                               'kde position entropy', 'kde bandwidth', 'recurrent p-value',
                                               'entropy p-value', 'kde entropy p-value', 'kde bandwidth p-value'])

        # get benjamani hochberg adjusted p-values
        permutation_df['recurrent BH q-value'] = utils.bh_fdr(permutation_df['recurrent p-value'])
        permutation_df['entropy BH q-value'] = utils.bh_fdr(permutation_df['entropy p-value'])
        permutation_df['kde entropy BH q-value'] = utils.bh_fdr(permutation_df['kde entropy p-value'])
        permutation_df['kde bandwidth BH q-value'] = utils.bh_fdr(permutation_df['kde bandwidth p-value'])

        # include non-tested genes in the result
        no_test_df = pd.DataFrame(index=range(len(non_tested_genes)))
        no_test_df['Performed Recurrency Test'] = 0
        no_test_df['gene'] = non_tested_genes
        permutation_df = pd.concat([permutation_df, no_test_df])
        permutation_df['Performed Recurrency Test'] = permutation_df['Performed Recurrency Test'].fillna(1).astype(int)

        # save output
        permutation_df['num recurrent'] = permutation_df['num recurrent'].fillna(-1).astype(int)  # fix dtype isssue
        col_order = ['gene', 'num recurrent', 'position entropy', 'kde position entropy', 'kde bandwidth',
                     'recurrent p-value', 'recurrent BH q-value', 'entropy p-value', 'entropy BH q-value',
                     'kde entropy p-value', 'kde entropy BH q-value', 'kde bandwidth p-value',
                     'kde bandwidth BH q-value', 'Performed Recurrency Test']
        permutation_df[col_order].to_csv(opts['output'], sep='\t', index=False)
    else:
        permutation_df = pd.DataFrame(sorted(permutation_result, key=lambda x: x[2]),
                                      columns=['gene', 'num deleterious', 'deleterious p-value'])
        tmp_df = permutation_df[permutation_df['deleterious p-value'].notnull()]

        # get benjamani hochberg adjusted p-values
        permutation_df['deleterious BH q-value'] = np.nan
        permutation_df['deleterious BH q-value'][tmp_df.index] = utils.bh_fdr(tmp_df['deleterious p-value'])

        # sort output by p-value. due to no option to specify NaN order in
        # sort, the df needs to sorted descendingly and then flipped
        permutation_df = permutation_df.sort(columns='deleterious p-value', ascending=False)
        permutation_df = permutation_df.reindex(index=permutation_df.index[::-1])

        # save result
        permutation_df.to_csv(opts['output'], sep='\t', index=False)

    return permutation_df


if __name__ == "__main__":
    opts = parse_arguments()
    main(opts)
