from bidict import bidict
from bson.objectid import ObjectId
from collections import Counter, defaultdict
from math import ceil, floor
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from pprint import pprint
from sklearn.feature_extraction.text import TfidfVectorizer
from pyfasttext import FastText
import argparse
import json
import numpy as np
from collections import namedtuple
import os
import pandas as pd
import pickle
import json
import errno
import random
import re

DataPoint = namedtuple('DataPoint', ['id', 'sequence'])

def get_top_k_funcs(k, df, df_col):
    """
    @:returns The the sub series of the top-k unique job title counts
    """
    toplist = df[df_col].value_counts()
    last_count = toplist[k]
    return toplist[toplist >= last_count].index.values

def get_valid_ids(df, toplist, df_col):
    """
    @returns the set of user profile IDs that only use job titles within the toplist.
    """

    bad_ids = df[~df[df_col].isin(toplist)]["_id"].unique()
    all_ids = df["_id"].unique()

    return  list(set(all_ids) - set(bad_ids))

def get_id_sets(dataset_ids, path, use_cached=False):
    """
    splits dataset ids into profile ids that will be used for
    training the models and ids for testing the models
    @:returns tuple (train_ids, test_ids)
    """
    if os.path.exists(os.path.join(path, 'train_ids.pkl')) and use_cached:
        print("Loading already existing train and test ids...")
        train_ids = load(os.path.join(path, 'train_ids.pkl'), pickle)
        test_ids = load(os.path.join(path, 'test_ids.pkl'), pickle)
    else:
        print("Pre split train and test ids not found, randomly splitting now...")
        random.seed(1234)
        train_size = ceil(0.8 * len(dataset_ids))
        random.shuffle(dataset_ids)
        train_ids = dataset_ids[:train_size]
        test_ids = dataset_ids[train_size:]

    return train_ids, test_ids

def dump(path, serializer, obj):
    """
    Saves 'obj' to 'path' using 'serializer' (either pickle or json)
    """
    if not os.path.exists(os.path.dirname(path)):
        try:
            os.makedirs(os.path.dirname(path))
        except OSError as exc:  # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

    mode = "wb" if serializer.__name__ == "pickle" else "w"
    print(f"Writing to {path}")
    with open(path, mode) as f:
        serializer.dump(obj, f)

def load(path, serializer):
    """
    Loads and returns an object from 'path' by using 'serializer' (pickle or json)
    """
    print(f"Loading from {path} with {serializer}...")
    mode = "rb" if serializer.__name__ == "pickle" else "r"
    with open(path, mode) as f:
        dat = serializer.load(f)

    return dat

def get_sequences(df, df_col, title_id, train_ids, test_ids, use_ids=True):
    """
    Returns tuple of (train_sequences, test_sequences) which are both
    lists of lists of job title ids if use_ids == True else: they are lists of job
    title strings

    @:returns tuple of (train_sequences, test_sequences)
    """
    func_series = df.groupby('_id')[df_col].apply(lambda x: list(reversed(list(x))))

    if use_ids:
        train_data = [DataPoint(i, [title_id[title] for title in func_series[i]]) for i in train_ids]
        test_data = [DataPoint(i, [title_id[title] for title in func_series[i]]) for i in test_ids]
    else:
        train_data = [DataPoint(i, [title for title in func_series[i]]) for i in train_ids]
        test_data = [DataPoint(i, [title for title in func_series[i]]) for i in test_ids]

    return train_data, test_data

def _get_bow(funcs):
    """
    Retruns (vocabulary to id mapping, tokenizer_pattrn)
    """
    sw = set(stopwords.words("english"))
    joined = " ".join(funcs)
    pattrn = re.compile(r"[-/,\.\\\s]")
    tokens = re.split(pattrn, joined)
    vocab = set(tokens)

    vocab = vocab - sw
    vocab = vocab - {''}

    vocab_id = {token: i for i, token in enumerate(vocab)}

    return vocab_id, pattrn

def as_bows(df, df_col, title_id, train_ids, test_id, tf_idf=True):
    """
    Represent each word in a job title as a bag-of-words.
    @return: list of bow sequences
    """
    train, test = get_sequences(df, df_col, title_id, train_ids, test_id, use_ids=False)
    vocab_id, pattrn = _get_bow(list(title_id.keys()))
    bow = {}

    for title in title_id.keys():
        tokens = re.split(pattrn, title)
        token_indices = [vocab_id[tok] for tok in tokens if tok in vocab_id]
        bow[title] = sorted(token_indices)

    train = [DataPoint(ex.id, [bow[title] for title in ex.sequence[:-1]]) for ex in train]
    test = [DataPoint(ex.id, [bow[title] for title in ex.sequence[:-1]]) for ex in test]

    return train, test, vocab_id

def get_job_embs(title_id, emb_dim=300, model_path="/data/rali7/Tmp/solimanz/data/wikipedia/wiki.en.bin"):
    """
    Returns a matrix of job title embeddings
    """
    print("Loading fastText model...")
    model = FastText(model_path)
    print("Model successfull loaded :-D")

    embeddings = np.zeros((len(title_id), emb_dim), dtype=np.float32)

    for title in title_id.keys():
        vec = model.get_sentence_vector(title)
        embeddings[title_id[title], :] = vec

    return embeddings

def create_path(path):
    if not os.path.exists(path):
        print(f"Attempting to create path {path}...")
        try:
            os.makedirs(path)
        except OSError as exc:  # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise
    else:
        print(f"Path {path} already exists")

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Script to help generate datasets')
    parser.add_argument('-ds', '--dataset', required=True, help='method to standardize dataset',
                    choices=['top550', 'reduced7000'])
    parser.add_argument('-m', '--model', required=True, help='Model for which to build a feature representation for',
                        choices=['mlp', 'simple_rnn'])
    parser.add_argument('-r', '--representation', required=True, help='Choose a method to represent textual data',
                        choices=['jobid', 'bow', 'title_emb', 'emb', 'all'])
    args = parser.parse_args()

    col_options = {
        'top550': 'transformed',
        'reduced7000': 'reduced'
    }
    data_repr = ['jobid', 'bow', 'title_emb']

    # Setting path for saving data
    if args.model == 'simple_rnn':
        ds_path = f"/data/rali7/Tmp/solimanz/data/datasets/{args.dataset}"
    else:
        ds_path = f"/data/rali7/Tmp/solimanz/data/datasets/feed_forward/{args.dataset}"

    # Name of the data file
    if args.model =='simple_rnn':
        ds_file_name = "title_sequences"
    else:
        ds_file_name = "data"

    # Set number of labels
    if args.dataset == 'top550':
        k = 550
    else :
        k = 7000

    # Get the column of the coressponding the the dataset
    df_col = col_options[args.dataset]
    ds = args.dataset
    df_path = "/data/rali7/Tmp/solimanz/data/pickles/excerpt-2017-02-20_reduced.pkl"

    print("Reading dataframe...")
    df = pd.read_pickle(df_path)
    print("Successfully loaded dataframe... :-D")
    top = get_top_k_funcs(k, df, df_col)
    print(f"Number of job labels: {len(top)}")
    dataset_ids = get_valid_ids(df, top, df_col)
    print(f"Size of entire dataset: {len(dataset_ids)}")

    print("Mapping job titles to integer ids...")
    title_id = {title: i for i, title in enumerate(top)}
    print(f"Number of unique job titles: {len(title_id)}")

    print("Splitting up dataset (test/train)...")
    train_ids, test_ids = get_id_sets(dataset_ids, f"/data/rali7/Tmp/solimanz/data/datasets/{args.dataset}",
                                      use_cached=False)
    print(f"Size of train: {len(train_ids)}\nSize of test: {len(test_ids)}")

    print("Saving test and train id lists...")
    dump(os.path.join(ds_path, 'train_ids.pkl'), pickle, train_ids)
    dump(os.path.join(ds_path, 'test_ids.pkl'), pickle, test_ids)

    print("Getting job sequences for train and test datasets...")

    if args.model == 'simple_rnn':
        print("making datasets for rnn...")
        if args.representation == 'jobid' or args.representation == 'all':
            print("Getting job title id sequences...")
            train, test = get_sequences(df, df_col, title_id, train_ids, test_ids)

            max_train_seq = max([len(ex.sequence) for ex in train])
            max_test_seq = max([len(ex.sequence) for ex in test])

            print(f"Maximum length of training sequences : {max_train_seq}"
                  f"\nMaximum length of test sequences: {max_test_seq}")

            print("Dumping job title id sequences...")

            data = {
                'title_to_id': title_id,
                'train_data': train,
                'test_data': test,
                'maximum_seq_len': max(max_train_seq, max_test_seq)
            }

            dump(os.path.join(ds_path, 'jobid', 'data.json'), json, data)

        if args.representation == 'bow' or args.representation == 'all':
            print("Getting job title bow sequences...")
            train_bow, test_bow, vocab = as_bows(df, df_col, title_id, train_ids, test_ids)
            train, test = get_sequences(df, df_col, title_id, train_ids, test_ids)

            max_train_seq = max([len(ex.sequence) for ex in train_bow])
            max_test_seq = max([len(ex.sequence) for ex in test_bow])

            train_targets = [DataPoint(ex.id, ex.sequence[1:]) for ex in train]
            test_targets =  [DataPoint(ex.id, ex.sequence[1:]) for ex in test]

            print(f"Maximum length of training sequences : {max_train_seq}"
                  f"\nMaximum length of test sequences: {max_test_seq}")
            print("Dumping job title id sequences...")
            data = {
                'title_to_id': title_id,
                'train_data': train_bow,
                'test_data': test_bow,
                'train_targets': train_targets,
                'test_targets': test_targets,
                'vocab': vocab,
                'maximum_seq_len': max(max_train_seq, max_test_seq)
            }
            dump(os.path.join(ds_path, 'bow', 'data.json'), json, data)

        if args.representation == 'title_emb' or args.representation == 'all':
            print("Getting embeddings...")
            embeddings = get_job_embs(title_id)

            if not os.path.exists(os.path.join(ds_path, "title_emb")):
                print("Attempting to create directory...")
                try:
                    os.makedirs(os.path.join(ds_path, "title_emb"))
                except OSError as exc:  # Guard against race condition
                    if exc.errno != errno.EEXIST:
                        raise
            print("Saving embedding matrix...")
            np.save(os.path.join(ds_path, "title_emb", "embeddings.npy"), embeddings)
            print("All done! :-D")

    elif args.model == 'mlp':

        train, test = get_sequences(df, df_col, title_id, train_ids, test_ids, use_ids=False)
        train_targets = [title_id[ex.sequence[-1]] for ex in train]
        test_targets = [title_id[ex.sequence[-1]] for ex in test]

        train_targets = np.eye(len(title_id))[train_targets]
        test_targets = np.eye(len(title_id))[test_targets]

        train = [" ".join(ex.sequence[:-1]) for ex in train]
        test = [" ".join(ex.sequence[:-1]) for ex in test]

        if args.representation == 'bow' or args.representation == 'all':

            print("Working on TF-IDF representation...")
            vect = TfidfVectorizer(stop_words=stopwords.words("english"))
            vect.fit(train + test)

            X_train = vect.transform(train).todense()
            X_test = vect.transform(test).todense()

            create_path(os.path.join(ds_path, 'bow'))

            print("Saving train and test matrices...")
            np.save(os.path.join(ds_path, "bow", "train.npy"), X_train)
            np.save(os.path.join(ds_path, "bow", "test.npy"), X_test)
            np.save(os.path.join(ds_path, "bow", "train_targets.npy"), train_targets)
            np.save(os.path.join(ds_path, "bow", "test_targets.npy"), test_targets)
            print("All done! :-D")

        if args.representation == 'title_emb' or args.representation == 'all':

            print("Loading pre trained fastText model...")
            model = FastText("/data/rali7/Tmp/solimanz/data/wikipedia/wiki.en.bin")

            X_train = np.zeros((len(train), 300), dtype=np.float32)
            X_test = np.zeros((len(test), 300), dtype=np.float32)

            for i, job_hist in enumerate(train):
                vec = model.get_sentence_vector(job_hist)
                X_train[i, :] = vec

            for i, job_hist in enumerate(test):
                vec = model.get_sentence_vector(job_hist)
                X_test[i, :] = vec

            create_path(os.path.join(ds_path, 'emb'))

            print("Saving train and test embeddings...")
            np.save(os.path.join(ds_path, "emb", "train.npy"), X_train)
            np.save(os.path.join(ds_path, "emb", "test.npy"), X_test)
            np.save(os.path.join(ds_path, "emb", "train_targets.npy"), train_targets)
            np.save(os.path.join(ds_path, "emb", "test_targets.npy"), test_targets)
            print("All done! :-D")