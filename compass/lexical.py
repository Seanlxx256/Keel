"""Small deterministic BM25 reference shared by repository and corpus evaluation."""
from collections import Counter
import math
import re


def tokens(text):
    originals = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
    split = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).replace("_", " ")
    return originals + re.findall(r"\w+", split.casefold(), flags=re.UNICODE)


class BM25:
    def __init__(self, documents):
        self.documents = [(identifier, Counter(tokens(text))) for identifier, text in documents]
        if len({identifier for identifier, _ in self.documents}) != len(self.documents):
            raise ValueError("BM25 document IDs must be unique")
        self.frequency = Counter(term for _, counts in self.documents for term in counts)
        self.lengths = {identifier: sum(counts.values()) for identifier, counts in self.documents}
        self.average = sum(self.lengths.values()) / max(1, len(self.documents))

    def search(self, query, limit, *, allowed=None, check=lambda: None):
        terms = set(tokens(query))
        found = []
        for identifier, counts in self.documents:
            check()
            if allowed is not None and identifier not in allowed:
                continue
            score = 0.0
            for term in terms:
                count = counts.get(term, 0)
                if count:
                    idf = math.log(1 + (len(self.documents) - self.frequency[term] + 0.5) / (self.frequency[term] + 0.5))
                    score += idf * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * self.lengths[identifier] / (self.average or 1)))
            if score > 0:
                found.append({"id": identifier, "bm25_score": score})
        found.sort(key=lambda row: (-row["bm25_score"], row["id"]))
        return found[:limit]
