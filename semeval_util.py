import pickle
import string
import XMLParser
import nltk
import scipy
from nltk.corpus import conll2000
from nltk.chunk.util import conlltags2tree
from nltk.stem.lancaster import LancasterStemmer
from nltk.stem.porter import PorterStemmer
import re
import cPickle
from sklearn import cross_validation
from collections import defaultdict
import os
import sys
import itertools
import copy
import heapq
import codecs
import semevalTask4

'''
This file contains utility methods used for multiple subtasks of semeval Task4
'''

negateWords = ["won't", "wouldn't", "shan't", "shouldn't", "can't", "cannot", "couldn't", "mustn't",
               "isn't" "aren't" "wasn't" "weren't" "hasn't" "haven't" "hadn't" "doesn't" "don't" "didn't",
               "not", "no", "never", "n't",
               "wont", "wouldnt", "shant", "shouldnt", "cant", "couldnt", "mustnt", "isnt", "arent",
               "wasnt", "werent", "hasnt", "havent", "hadnt", "doesnt", "dont", "didnt"]


def train_and_trial(trn_file, test_file, clf, posit_lex_file='positive-words.txt', nega_lex_file='negative-words.txt',
                    pickled=False):
    """ Train on the training file and test on the testing file,
    given a classifier, for the aspect extraction task.
    """
    if pickled:
        f = open(trn_file, 'rb')
        traind = cPickle.load(f)
        f.close()
        f = open(test_file, 'rb')
        testd = cPickle.load(f)
        f.close()
    else:
        traind = XMLParser.create_exs(trn_file)
        testd = XMLParser.create_exs(test_file)
    posi_words = semeval_util.get_liu_lexicon(posit_lex_file)
    negi_words = semeval_util.get_liu_lexicon(nega_lex_file)
    senti_dictionary = semeval_util.get_mpqa_lexicon()
    #chunker = ConsecutiveChunker(traind['iob'], senti_dictionary)
    chunker = clf.train(traind['iob'], senti_dictionary)
    print "done training"

    guessed_iobs = chunker.evaluate(testd['iob'])
    XMLParser.create_xml(testd['orig'], guessed_iobs,testd['id'],testd['idx'],'trial_answers.xml')
    compute_pr(testd['iob'], guessed_iobs)



#We are not using this, it's just an example to play around with chunking from the NLTK book
class UnigramChunker(nltk.ChunkParserI):
    def __init__(self, train_sents): # [_code-unigram-chunker-constructor]
        train_data = [[(t,c) for w,t,c in nltk.chunk.tree2conlltags(sent)]
                      for sent in train_sents]
        self.tagger = nltk.UnigramTagger(train_data) # [_code-unigram-chunker-buildit]

    def parse(self, sentence): # [_code-unigram-chunker-parse]
        pos_tags = [pos for (word,pos) in sentence]
        tagged_pos_tags = self.tagger.tag(pos_tags)
        chunktags = [chunktag for (pos, chunktag) in tagged_pos_tags]
        conlltags = [(word, pos, chunktag) for ((word,pos),chunktag)
                     in zip(sentence, chunktags)]
        #print "input to conlltags", conlltags
        return conlltags2tree(conlltags)


def vocabulary(train_sentences):
    """Experiments with dealing with unknown words.
    """
    #unique vocabulary
    vocab = set()
    #all words for counting most frequent
    wd_dist = []
    for tagged_sent in train_sentences:
        untagged_sent = nltk.tag.untag(tagged_sent)
        for (w, _t) in untagged_sent:

            vocab.add(w.lower())
            wd_dist.append(w.lower())
    print "# of vocab words:", len(vocab)
    distro = nltk.FreqDist(wd_dist)
    topn = int(len(vocab) * 0.5)
    return list(distro)[:topn]


def get_objectivity(sentiment):
    result = 'neutral'
    if sentiment == 'positive' or sentiment == 'negative':
        result = 'obj'
    return result


def create_sentiment_sequence(iobs, senti_dictionary, negate_wds=negateWords):
    """New idea in late March: label each iob with a sentiment based on punctuation boundaries, etc.
    This part just does one sentence.
    Break up the sentence by its punctuation. Between each punctuation boundary, count the
    positive & negative sentiment words, and also track negation words.
    Label all iobs within a punc window with the same polarity.
    """
    punctuation_list = [c for c in string.punctuation]
    use_conj = False
    if use_conj:
        punctuation_list.extend(['CC'])
    #indices for locations of punctuation, subjective words, and negation words
    punc_idxs, subj_idxs, neg_idxs = [], [], []
    polarities = []
    for i, (w, pos, iob) in enumerate(iobs):
        if w in punctuation_list or pos in punctuation_list:
            punc_idxs.append(i)
        if w in negate_wds:
            neg_idxs.append(i)
        polarity = sentiment_lookup(senti_dictionary, w, pos)
        if polarity != 'neutral':
            subj_idxs.append(i)
            polarities.append(polarity)
    #add punctuation at end if not there
    if not punc_idxs:
        punc_idxs.append(len(iobs)-1)
    #print punc_idxs, neg_idxs
    #print subj_idxs, polarities
    #second pass to calculate polarities within each punc boundary
    results = []
    s_idx, n_idx = 0, 0
    prev = -1
    for p_idx in range(len(punc_idxs)):
        negate = 1
        curr_punc_idx = punc_idxs[p_idx]
        while n_idx < len(neg_idxs) and neg_idxs[n_idx] < curr_punc_idx:
            negate *= -1
            n_idx += 1
        pos_ctr, neg_ctr = 0, 0
        while s_idx < len(subj_idxs) and subj_idxs[s_idx] < curr_punc_idx:
            if polarities[s_idx] == 'positive':
                pos_ctr += 1
            elif polarities[s_idx] == 'negative':
                neg_ctr += 1
            s_idx += 1
        if negate == 1:
            this_chunk_tag = (pos_ctr, neg_ctr)
        else:
            this_chunk_tag = (neg_ctr, pos_ctr)
        results.extend([this_chunk_tag] * (curr_punc_idx - prev))
        prev = curr_punc_idx
    #WE know there are sometimes bugs, ignore for now (last hours)
    #if len(results) != len(iobs):
    #    print "BUG"
    # If there are not enough polarities, extend the last one
    # If there are too many, the later processing will ignore the extras
    len_r = len(results)
    if len_r < len(iobs):
        diff = len(iobs) - len_r
        results.extend([results[len_r-1]] * diff)
    return results


def dep_features(sentence, i, parse):
    """ Create the features related to dependency parsing.
    Assumes dependency parsing has already been done and our DepTree representation is passed in.
    Print some debugging information in some cases.
    Returns a dictionary of feature values for the window around position i in sentence.
    """
    debug = False
    word, pos = sentence[i]
    target = "%s-%d" % (word, i+1)
    if target in parse.elements:
        dep_node = parse.elements[target]
        dist_w = dep_node.closest_sentiment
        sent_w = dep_node.polarity_closest
    else:
        if pos != '.' and word != ',' and pos != 'CC' and pos != 'IN' and pos != 'TO'\
                and pos != 'WDT' and pos != ':':
            if debug:
                #print "IOB %s at posit %d not found in parse:\n %s" % (sentence[i], i+1, parse)
                print "IOB %s at posit %d not found in parse" % (sentence[i], i+1)
        dist_w = sys.maxint
        sent_w = 'neutral'
    #prevw stuff
    if i == 0:
        dist_p = "<START>"
        sent_p = "<START>"
    else:
        prevw, prevpos = sentence[i-1]
        target = "%s-%d" % (prevw, i)
        if target in parse.elements:
            dep_node = parse.elements[target]
            dist_p = dep_node.closest_sentiment
            sent_p = dep_node.polarity_closest
        else:
            dist_p = sys.maxint
            sent_p = 'neutral'
    #next wd stuff
    if i == len(sentence)-1:
        dist_n = "<END>"
        sent_n = "<END>"
    else:
        nextw, nextpos = sentence[i+1]
        target = "%s-%d" % (nextw, i+2)
        if target in parse.elements:
            dep_node = parse.elements[target]
            dist_n = dep_node.closest_sentiment
            sent_n = dep_node.polarity_closest
        else:
            dist_n = sys.maxint
            sent_n = 'neutral'
    return {'dep_distw': dist_w, 'dep_sent': sent_w, 'dep_distp': dist_p, 'dep_sentp': sent_p,
            'dep_distn': dist_n, 'dep_sentn': sent_n}


def sentiment_lookup(dict, word, pos):
    """ Return a sentiment indicator for the given word with the given POS tag, according to the dictionary.
    Return values: positive, negative, neutral.
    Uses stemming if not found with original word
    """
    word = word.lower()
    result = senti_idx_aux(dict, word, pos)
    if result == 'neutral':
        stemmer = LancasterStemmer()
        stemmed = stemmer.stem(word)
        result = senti_idx_aux(dict, stemmed, pos)
    if result == 'neutral':
        stemmer = PorterStemmer()
        stemmed = stemmer.stem(word)
        result = senti_idx_aux(dict, stemmed, pos)
    return result


def senti_idx_aux(dict, word, pos):
    #deal with POS - find more specific lexicon entries first
    if pos.startswith('NN'):
        if (word, 'noun') in dict['pos'] or (word,'anypos') in dict['pos']:
            return 'positive'
        if (word, 'noun') in dict['neg']or (word,'anypos') in dict['neg']:
            return 'negative'
    elif pos.startswith('JJ'):
        if (word,'adj') in dict['pos']or (word,'anypos') in dict['pos']:
            return 'positive'
        if (word,'adj') in dict['neg']or (word,'anypos') in dict['neg']:
            return 'negative'
    elif pos.startswith('VB'):
        if (word,'verb') in dict['pos'] or (word,'anypos') in dict['pos']:
            return 'positive'
        if (word,'verb') in dict['neg']or (word,'anypos') in dict['neg']:
            return 'negative'
    elif pos.startswith('RB'):
        if (word,'adverb') in dict['pos'] or (word,'anypos') in dict['pos']:
            return 'positive'
        if (word,'adverb') in dict['neg']or (word,'anypos') in dict['neg']:
            return 'negative'
    if word in dict['pos']:
        return 'positive'
    if word in dict['neg']:
        return 'negative'
    return 'neutral'


def compute_pr(c_iobs, g_iobs):
    """Compute precision, recall, and F1 for aspect labeling task
    (rough approach, only tracks "B" tags)
    """
    debug = False
    tp = 0
    fp = 0
    n = 0
    print "num examples:", len(c_iobs)
    for i in range(len(c_iobs)):
        one_corr = c_iobs[i]
        one_guess = g_iobs[i]
        #just counting the first word in each aspect phrase
        begin_terms = [x[0] for x in one_corr if x[2].startswith('B')]
        n += len(begin_terms)
        print_this = False
        #iterate through the guesses finding aspect term beginnings
        for j in range(len(one_guess)):
            if one_guess[j][2].startswith('B'):
                if one_guess[j][0] in begin_terms:
                    tp += 1
                else:
                    fp += 1
                    print_this = True
        if debug and (print_this or tp < len(begin_terms)):
            print "FPs: %s true:\n %s;\n guess:\n %s" %(print_this, one_corr, one_guess)
    print "num terms:", n
    print "num guesses:", tp+fp
    recall = 0.
    if n > 0:
        recall = float(tp)/n
    if (tp+fp) > 0:
        precision = float(tp)/(tp + fp)
    else:
        precision = 1.0
    if tp > 0:
        f1 = (2 * precision * recall)/(precision + recall)
    else:
        f1 = 0
    print "Recall %.2f, Precision: %.2f, F1 %.2f" %(recall, precision, f1)
    return recall, precision, f1


def compute_sent_acc(c_labels, g_labels):
    corr_count = 0.
    n = 0.
    print "num examples:", len(c_labels)
    for i in range(len(c_labels)):
        one_corr = c_labels[i]
        one_guess = g_labels[i]
        for j in range(len(one_corr)):
            if one_corr[j] == one_guess[j]:
                corr_count += 1
            n += 1
    if n > 0:
        acc = corr_count/n
    else:
        acc = 0.
    print "correct:", corr_count, "actual:", n
    print "Sentiment labeling acc", acc
    return acc


def get_liu_lexicon(filename):
    """
    Return the list of sentiment words from the Liu-formatted sentiment lexicons (just a header then a list)
    """
    return [item.strip() for item in open(filename, "r").readlines() if re.match("^[^;]+\w",item)]


def get_mpqa_lexicon(filename='subjclueslen1-HLTEMNLP05.tff'):
    """ Returns a dictionary of word/polarity/POS triples given a filename
    containing the MPQA subjectivity lexicon.
    Include in the dictionary all seen POS tags
    """
    with open(filename, 'r') as text:
        lines = text.readlines()
    results = defaultdict(list)
    pos_tags = set()
    for entry in lines:
        info = entry.strip().split()
        if len(info) == 6:
            word = info[2].split('=')[1]
            pos_tag = info[3].split('=')[1]
            pos_tags.add(pos_tag)
            polarity = info[5].split('=')[1]
            if polarity == 'positive':
                results['pos'].append((word, pos_tag))
            elif polarity == 'negative':
                results['neg'].append((word, pos_tag))
            elif polarity == 'neutral':
                results['neutral'].append((word, pos_tag))
            elif polarity == 'both':
                results['pos'].append((word, pos_tag))
                results['neg'].append((word, pos_tag))
            else:
                print "unexpected lexicon entry:", info
        else:
            pairs = [item.split('=') for item in info]
            polarity = [p[1] for p in pairs if p[0]=='priorpolarity']
            word = [p[1] for p in pairs if p[0]=='word1']
            if len(polarity) != 1 or len(word) != 1:
                print "malformed line?", info
            else:
                pos_tag = [p[1] for p in pairs if p[0]=='pos1']
                if len(pos_tag) == 1:
                    pos_tags.add(pos_tag[0])
                    if polarity[0] == 'positive':
                        results['pos'].append((word[0], pos_tag[0]))
                    elif polarity[0] == 'negative':
                        results['neg'].append((word[0], pos_tag[0]))
                    elif polarity[0] == 'neutral':
                        results['neutral'].append((word[0], pos_tag[0]))
                    elif polarity[0] == 'both':
                        results['pos'].append((word[0], pos_tag[0]))
                        results['neg'].append((word[0], pos_tag[0]))
                    else:
                        print "unexpected lexicon entry:", info
                else:
                    print "missing or unexpected pos tag:", info
                    if polarity[0] == 'positive':
                        results['pos'].append(word[0])
                    elif polarity[0] == 'negative':
                        results['neg'].append(word[0])
                    elif polarity[0] == 'neutral':
                        results['neutral'].append(word[0])
                    elif polarity[0] == 'both':
                        results['pos'].append(word[0])
                        results['neg'].append(word[0])
                    else:
                        print "unexpected lexicon entry:", info
            pass
    results['pos_tags'] = pos_tags
    return results


def create_parses_from_dict(input, ofile='dep_parse.txt', pickled=True):
    if pickled:
        f = open(input, 'rb')
        traind = cPickle.load(f)
        f.close()
    else:
        traind = XMLParser.create_exs(input)
    return stanford_parse(traind['orig'], ofile)


def stanford_parse(sentences, ofile='dep_parse.txt'):
    ''' Use the Stanford parser to parse the sentences
    and dump the results to a file.
    '''
    parses = []
    f = open(ofile, 'w')
    for sent in sentences:
        sent = sent.encode('utf-8')
        parser_out = parse_one_sent(sent.strip())
        if multi_sent(parser_out):
            parser_out = parse_one_sent(remove_dots(sent))
        dep_part = get_dep(parser_out)
        parses.append(dep_part)
        f.write(dep_part)
        f.write('\n')
    f.close()
    return parses


def parse_one_sent(words):
    os.popen("echo '"+words+"' > ~/stanfordtemp.txt")
    return os.popen('~/Documents/src/stanford-parser-full-2014-01-04/lexparser.sh ~/stanfordtemp.txt').readlines()


def multi_sent(parse):
    '''Words with abbreviations in them fool the parser, like "4 hrs."
    '''
    return len([i for i in parse if i=='(ROOT\n']) > 1


def remove_dots(sentence):
    return sentence.replace('.', '')


def get_dep(full_stanford_result):
    """ Helper function for stanford_parse
    Get just the dependency parse elements from the full stanford parse results
    (Starts with a parse tree)
    """
    result = ''
    dep_start = False
    for r in full_stanford_result:
        if dep_start:
            result = result + ' '+ r.strip()
        elif r.strip() == '':
            dep_start = True
    return result.strip()


def add_dep_parse_features(original, parse_file, pickled=True, dictionary=False, iobs=False):
    """Create the dependency tree dictionaries that we need for each sentence
    in the input corpus.
    Inputs:
    original: pickled version of our dictionary, or the dictionary itself,
    or the original XML file
    """
    if pickled and not dictionary:
        f = open(original, 'rb')
        traind = cPickle.load(f)
        f.close()
    elif dictionary:
        traind = original
    else:
        traind = XMLParser.create_exs(original)
    f = open(parse_file, 'r')
    lines = f.readlines()
    f.close()
    dep_trees = transform_dep_parse(lines)
    senti_dictionary = get_mpqa_lexicon()
    if iobs:
        new_dep_trees = integrate_dep_iob(traind, dep_trees, senti_dictionary)
    else:
        new_dep_trees = integrate_dep_iob(traind['iob'], dep_trees, senti_dictionary)
    return new_dep_trees


def integrate_dep_iob(iobs, dep_ps, senti_dict):
    """Adds information to the dep parse structure about the closest polarity-bearing term:
    -its distance in the dependency parse, and -its polarity
    """
    result = dep_ps
    for i in range(len(iobs)):
        iob = iobs[i]
        #print iob
        parse = dep_ps[i]
        #print parse
        for j in range(len(iob)):
            (w, pos, _iob_label) = iob[j]
            polarity = sentiment_lookup(senti_dict, w, pos)
            if polarity != 'neutral':
                result[i] = update_dist(parse, w, j, polarity)
                #print "for w: %s, polarity %s, new result: %s" % (w, polarity, result[i])
    return result


def update_dist(parse, word, position, polarity):
    #print "orig in update", parse
    #print word, position
    target = "%s-%d" % (word, position+1)
    for node in parse.elements:
        distance = parse.find_path_dist(target, node)
        closest = parse.elements[node].closest_sentiment
        if distance < closest:
            parse.elements[node].closest_sentiment = distance
            closest = distance
            parse.elements[node].polarity_closest = polarity
        distance = parse.find_path_dist(node, target)
        if distance < closest:
            parse.elements[node].closest_sentiment = distance
            parse.elements[node].polarity_closest = polarity
        if distance == sys.maxint:
            print "%s not found in parse: %s" % (target, parse)
    #print "update_dist ret:", parse
    return parse


def constant_factory(value):
    return itertools.repeat(value).next


def test_dep_parsing(file, to_test):
    f = open(file, 'r')
    lines = f.readlines()
    f.close()
    dep_trees = transform_dep_parse(lines)
    results = []
    for n in range(to_test):
        test_tree = dep_trees[n]
        print "test tree:", test_tree
        results.append(find_distances(test_tree))
    return results


def find_distances(test_tree):
    """Tested on all laptop sentences (small) at least doesn't crash.
    """
    results = {}
    leaves = test_tree.get_leaves()
    for node1 in test_tree.elements:
        #print node1
        #print "TOP results so far",results
        found = False
        if node1 in results:
            found = True
        for node2 in test_tree.elements:
            distance = test_tree.find_path_dist(node1, node2)
            if not found:
                if node2 in results:
                    if node1 in results[node2]:
                        if distance < results[node2][node1]:
                            results[node2][node1] = distance
                    else:
                        results[node2][node1] = distance
                else:
                    results[node1] = {}
                    results[node1][node2] = distance
                    found = True
            else:
                if node2 in results[node1]:
                    if distance < results[node1][node2]:
                        results[node1][node2] = distance
                else:
                    results[node1][node2] = distance
        if not found:
            results[node1] = {}
        for node2 in leaves:
            distance = test_tree.find_path_dist(node1, node2)
            if node2 in results[node1]:
                if distance < results[node1][node2]:
                    results[node1][node2] = distance
            else:
                results[node1][node2] = distance
            #print "res:", distance
    #print "FINAL\n", results
    return results


class Queue:
    "A container with a first-in-first-out (FIFO) queuing policy."
    def __init__(self):
        self.list = []

    def push(self,item):
        "Enqueue the 'item' into the queue"
        self.list.insert(0,item)

    def pop(self):
        """
          Dequeue the earliest enqueued item still in the queue. This
          operation removes the item from the queue.
        """
        return self.list.pop()

    def isEmpty(self):
        "Returns true if the queue is empty"
        return len(self.list) == 0


class PriorityQueue:
    """
      Implements a priority queue data structure. Each inserted item
      has a priority associated with it and the client is usually interested
      in quick retrieval of the lowest-priority item in the queue. This
      data structure allows O(1) access to the lowest-priority item.

      Note that this PriorityQueue does not allow you to change the priority
      of an item.  However, you may insert the same item multiple times with
      different priorities.
    """
    def __init__(self):
        self.heap = []
        self.count = 0

    def push(self, item, priority):
        entry = (priority, self.count, item)
        heapq.heappush(self.heap, entry)
        self.count += 1

    def pop(self):
        (_, _, item) = heapq.heappop(self.heap)
        return item

    def isEmpty(self):
        return len(self.heap) == 0


def transform_dep_parse(parses):
    """Transform a raw dependency parse (from Stanford parser) to a format
    we can use, namely DepTree's
    """
    results = []
    for p in parses:
        #print p
        this_tree = DepTree()
        nodes = p.strip().split(')')
        for n in nodes:
            if n:
                n = n.strip()
                lp_idx = n.index('(')
                type = n[:lp_idx]
                pair = n[(lp_idx+1):].split(', ')
                this_tree.add_ele_pair(pair[0], pair[1], type)
        this_tree.get_leaves()
        this_tree.create_parents()
        results.append(this_tree)
    return results


class DepTree:
    """
    Dependency tree representation. Elements in the dictionary consist of head word as key and
    DepTreeEntry as entries.
    TODO is possibly subtract 1 from all positions because they are not the word's position in the sentence,
    because an extra "root" node is position 0
    """
    def __init__(self):
        self.elements = {}
        self.leaves = []
        self.has_parents = False

    def __repr__(self):
        res = ''
        for k in self.elements:
            res += '%s: %s\n' % (k, self.elements[k])
        return res

    def add_ele_pair(self, head, arg, name):
        #can't just split by hyphen because of hyphenated words
        h_idx = head.rindex('-')
        word = head[:h_idx]
        pos = head[(h_idx+1):]
        key = self.make_key(word, pos)
        if not self.elements.has_key(key):
            self.elements[key] = DepTreeEntry(pos)
        entry = self.elements[key]
        #h_idx = arg.rindex('-')
        entry.add_child(name, arg)
        #entry.add_child(name, [arg[:h_idx],arg[h_idx+1:]])

    def add_ele_leaf(self, leaf):
        h_idx = leaf.rindex('-')
        word = leaf[:h_idx]
        pos = leaf[(h_idx+1):]
        key = self.make_key(word, pos)
        if not self.elements.has_key(key):
            self.elements[key] = DepTreeEntry(pos)

    def make_key(self, word, position):
        #maintain original rep for now
        return '%s-%s' % (word, position)

    def get_leaves(self):
        if self.leaves:
            return self.leaves

        lvs = []
        for k, v in self.elements.items():
            children = v.children
            for (_arg_type, c) in children:
                if not c in self.elements:
                    lvs.append(c)
                    #also add to elements
                    self.add_ele_leaf(c)
        self.leaves = lvs
        return lvs

    def find_path_dist(self, key1, key2):
        """ Work in progress - think it works!
        """
        if (not key1 in self.elements) and (not key2 in self.elements):
            print "both of keys missing:", key1, key2
            return sys.maxint
        if key1 in self.elements:
            node1 = self.elements[key1]
        else:
            node1 = key1
        if key2 in self.elements:
            node2 = self.elements[key2]
        else:
            node2 = key2
        if node1 == node2:
            return 0
        #fringe = Queue()
        fringe = PriorityQueue()
        fringe.push((key1, []), 0)
        seen = []
        while True:
            if fringe.isEmpty():
                return sys.maxint
            state, path = fringe.pop()
            if not state in self.elements and state != node2:
                continue
            if state == node2:
                return len(path)

            state_node = self.elements[state]
            if state_node == node2:
                return len(path)
            if not state in seen:
                seen.append(state)
                if state in self.elements:
                    children = self.find_successors(state)
                    #print "successors of %s: %s" %(state, children)
                    for (_type, pair) in children:
                        newpath = path+[pair]
                        fringe.push((pair, newpath), len(newpath))

    def find_children(self, state):
        return self.elements[state].children

    def find_successors(self, state):
        children = copy.deepcopy(self.find_children(state))
        parents = copy.copy(self.get_parents(state))
        if parents:
            for p in parents:
                children.extend([('dc', p)])
        return children

    def get_parents(self, state):
        if self.has_parents:
            return self.elements[state].parent
        self.create_parents()
        return self.elements[state].parent

    def create_parents(self):
        """NOTE: may not find the closest parent. I'm ok with this since
        later we track distances to find closest nodes
        """
        #sometimes, there is no root, like if there's a fragment. Punt in that case - empty parents
        if 'ROOT-0' in self.elements:
            #root will only ever have one child
            kid = self.elements['ROOT-0'].children[0][1]
            fringe = Queue()
            fringe.push((kid, 'ROOT-0'))
            seen = []
            while True:
                if fringe.isEmpty():
                    self.has_parents = True
                    return
                state, parent = fringe.pop()
                if state in self.elements:
                    self.elements[state].parent.append(parent)
                if not state in seen and state in self.elements:
                    seen.append(state)
                    children = self.find_children(state)
                    for (_, pair) in children:
                        fringe.push((pair, state))


class DepTreeEntry:
    """
    A DepTreeEntry is a position, sentiment tag, and list of dependencies
    of the words at that position. It also tracks one of the parents of this node in the dep. tree.
    Dependencies themeselves are tuples looking like:
    (dep-type, [word, position]), for example (nsubj, [distribution, 10])
    """
    def __init__(self, posit, sentiment=None):
        self.parent = []
        self.position = posit
        self.sentiment = sentiment
        self.children = []
        self.closest_sentiment = sys.maxint
        self.polarity_closest = 'neutral'

    def __repr__(self):
        return ('%s, parents: %s sentiment: %d / %s\n%s' %(self.position, self.parent,
                                                           self.closest_sentiment, self.polarity_closest,
                                                           self.children))

    def add_child(self, type, pair):
        self.children.append((type, pair))

    def num_children(self):
        return len(self.children)


def K_fold_err_analysis(filename, parse_file,  k=5, p=0.15, pickled=False):
    """Does K-fold cross-validation on the given filename, but only p percent of it
    """

    if pickled:
        f = open(filename, 'rb')
        traind = cPickle.load(f)
        f.close()
    else:
        traind = XMLParser.create_exs(filename)
    #####
    n = int(len(traind['iob']) * p)
    dep_parses = traind['iob']
    #if use_dep_parse:
    #    dep_parses = add_dep_parse_features(traind['iob'], parse_file, dictionary=True, iobs=True)
    senti_dictionary = get_mpqa_lexicon()
    kf = cross_validation.KFold(n, n_folds=k, indices=True)
    tot_p, tot_r, tot_f1 = 0, 0, 0
    for train, test in kf:
        print "next fold, split size: %d/%d" %(len(train), len(test))
        #print train
        train_set = []
        test_set = []
        train_parse = []
        test_parse = []
        for i in train:
            train_set.append(traind['iob'][i])
            train_parse.append(dep_parses[i])
        for i in test:
            test_set.append(traind['iob'][i])
            test_parse.append(dep_parses[i])
        chunker = semevalTask4.ConsecutiveChunker(train_set, test_set, senti_dictionary, train_parse)
        guesses = chunker.evaluate([test_set, test_parse])
        r, p, f = compute_pr(test_set, guesses)
        tot_p += p
        tot_r += r
        tot_f1 += f
        #JUST ONE SPLIT FOR NOW!!!
        return
    print "ave Prec: %.2f, Rec: %.2f, F1: %.2f" %(tot_p/float(k), tot_r/float(k), tot_f1/float(k))


#Main to create the dependency parse features for a corpus
if __name__ == '__main__':
    """
    Here's how to do the parsing part:
    create_parses_from_dict('train.pkl','train-parse.txt')
    semeval_util.create_parses_from_dict('Rest_train_v2.pkl','rest_train-parse.txt')
    """
    #K_fold_err_analysis('../PycharmProjects/emnlp/Rest_train_v2.pkl',
    #                          'rest_train-parse.txt', pickled=True)
    f = open('Laptop_train_v2.pkl', 'rb')
    traind = cPickle.load(f)
    f.close()
    in_iob = False
    tot_bs, num_cooc = 0, 0
    num_sents = 0.
    for sentence in traind['iob']:
        num_sents += 1
        for _w,_pos,tag in sentence:
            if in_iob:
                if tag.startswith('B'):
                    tot_bs +=1
                    num_cooc += 1
                else:
                    in_iob = False
            elif tag.startswith('B'):
                in_iob = True
                tot_bs += 1
    print "aspect terms: %d, coocs: %d" %(tot_bs, num_cooc)
    print "num sents: %d, ave asps/sent %f" %(num_sents, tot_bs/num_sents)
