# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
"""Resolve dictionary senses and spelling candidates without guessing."""
import re
import unicodedata

_POS = r'verb|noun|adjective|adverb|preposition|pronoun|conjunction|auxiliary|numeral|interjection|vt|vi|adj|adv|ad|prep|pron|conj|aux|num|int|n|v|a'
_POS_CANONICAL = {'verb': 'v', 'vt': 'v', 'vi': 'v', 'noun': 'n', 'adjective': 'a', 'adj': 'a',
                  'adverb': 'adv', 'ad': 'adv', 'preposition': 'prep', 'pronoun': 'pron', 'conjunction': 'conj',
                  'auxiliary': 'aux', 'numeral': 'num', 'interjection': 'int'}


def normalize(text):
    text = unicodedata.normalize('NFKC', str(text or '')).lower()
    return re.sub(r'[\W_]+', '', text, flags=re.UNICODE)


def mean_parts(text):
    text = re.sub(r'\([^)]*\)|（[^）]*）', '', str(text or ''))
    text = re.sub(r'\b(?:' + _POS + r')(?:\.|\s|$)', '', text, flags=re.I)
    text = re.sub(r'\[[^\]]*\]', '', text)
    return {normalize(part) for part in re.split(r'[；;，,、/]', text) if normalize(part)}


def meanings_match(left, right):
    a, b = mean_parts(left), mean_parts(right)
    return bool(a and b and (a == b or a <= b or b <= a))


def part_of_speech(text):
    match = re.match(r'\s*(' + _POS + r')(?:\.|\s|$)', str(text or ''), re.I)
    if not match:
        return None
    tag = match.group(1).lower()
    return _POS_CANONICAL.get(tag, tag)


def senses(data):
    for sense in data.get('means') or []:
        examples = []
        for usage in sense.get('usages') or []:
            examples.extend(usage.get('examples') or [])
            examples.extend(usage.get('phrases_infos') or [])
            examples.extend(usage.get('mt_examples') or [])
        mean = sense.get('mean') or []
        yield ' '.join(mean) if isinstance(mean, list) else mean, examples
    for option in data.get('options') or []:
        content = option.get('content') or {}
        if isinstance(content, dict):
            yield content.get('mean', ''), (content.get('example') or []) + (content.get('usage_infos') or [])


def example_matches(stem, example):
    content, remark = stem.get('content'), stem.get('remark')
    return bool(
        (remark and normalize(remark) == normalize(example.get('sen_mean_cn')))
        or (content and normalize(content) == normalize(example.get('sen_content')))
    )


def answer_tag(option, index):
    tag = option.get('answer_tag')
    return index if tag is None else tag


def mean_choices(exam, data, contextual=False):
    rows = list(senses(data))
    if contextual:
        matched = [(mean, examples) for mean, examples in rows
                   if any(example_matches(exam.get('stem') or {}, ex) for ex in examples)]
        if matched:
            rows = matched
    tags = []
    for index, option in enumerate(exam.get('options') or []):
        content = option.get('content')
        if any(meanings_match(content, mean) and
               (not part_of_speech(content) or not part_of_speech(mean) or
                part_of_speech(content) == part_of_speech(mean)) for mean, _ in rows):
            tag = answer_tag(option, index)
            if tag not in tags:
                tags.append(tag)
    return tags


def choose_mean(exam, data, contextual=False):
    tags = mean_choices(exam, data, contextual)
    return tags[0] if len(tags) == 1 else None


def base_word(word, words, lemmatize):
    word = word.strip().lower()
    lookup = {str(w).lower(): w for w in words}
    if word in lookup:
        return lookup[word]
    candidates = []
    for ending in ('s', 'es', 'ed', 'ing'):
        if word.endswith(ending):
            stem = word[:-len(ending)]
            candidates.extend([stem, stem + 'e'])
            if len(stem) > 2 and stem[-1] == stem[-2]:
                candidates.append(stem[:-1])
    if word.endswith(('ies', 'ied')):
        candidates.append(word[:-3] + 'y')
    hits = {lookup[c] for c in candidates if c in lookup}
    if len(hits) == 1:
        return hits.pop()
    lemma = lemmatize(word)
    return lookup.get(str(lemma).lower(), lemma)


def word_forms(word):
    result = {word, word + 's', word + 'es', word + 'ed', word + 'ing'}
    if word.endswith('e'):
        result.update([word + 'd', word[:-1] + 'ing'])
    if len(word) > 1 and word.endswith('y') and word[-2] not in 'aeiou':
        result.update([word[:-1] + 'ies', word[:-1] + 'ied'])
    if len(word) >= 3 and word[-1] not in 'aeiouwxy' and word[-2] in 'aeiou' and word[-3] not in 'aeiou':
        result.update([word + word[-1] + 'ed', word + word[-1] + 'ing'])
    return result


def complete_word(info, query):
    exam = info.exam
    lengths = exam.get('w_lens') or []
    if len(lengths) != 1:
        return None
    length = int(lengths[0])
    tip = str(exam.get('w_tip') or '').strip().lower()
    stem = exam.get('stem') or {}
    candidates = {}
    for original in info.word_list:
        base = original.lower()
        fits = {w for w in word_forms(base) if len(w) == length and w.startswith(tip)}
        if not fits:
            continue
        query(info, original)
        for mean, examples in senses(info.word_query_result):
            for example in examples:
                if example_matches(stem, example):
                    for word in re.findall(r'\{([^{}]+)\}', example.get('sen_content') or ''):
                        word = word.strip().lower()
                        if len(word) == length and word.startswith(tip):
                            candidates[word] = max(candidates.get(word, 0), 3)
            if stem.get('remark') and meanings_match(stem['remark'], mean):
                for word in fits:
                    candidates[word] = max(candidates.get(word, 0), 2)
        for word in fits:
            candidates.setdefault(word, 1 if word == base else 0)
    if not candidates:
        return None
    best = max(candidates.values())
    winners = [word for word, score in candidates.items() if score == best]
    return winners[0] if len(winners) == 1 and best >= 1 else None
