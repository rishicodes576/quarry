"""Text-only ONNX inference: pinned weights, CPU execution, bounded batches, no image stack."""

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import mmh3
import numpy as np
import onnxruntime as ort
from py_rust_stemmers import SnowballStemmer
from tokenizers import Tokenizer

ort.disable_telemetry_events()


class Transformer:
    def __init__(self, directory: Path, model_file: str, max_length: int):
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=max_length)
        self.tokenizer.enable_padding(pad_id=0)
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
        self.model = ort.InferenceSession(
            str(directory / model_file), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.inputs = {item.name for item in self.model.get_inputs()}

    def infer(self, items):
        encoded = self.tokenizer.encode_batch(items)
        inputs = {
            "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
            "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
            "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
        }
        result = self.model.run(
            None, {key: value for key, value in inputs.items() if key in self.inputs}
        )[0]
        return result, inputs["attention_mask"]


class DenseEncoder(Transformer):
    def __init__(self, directory):
        config = json.loads((directory / "tokenizer_config.json").read_text())
        super().__init__(directory, "model.onnx", min(256, config["model_max_length"]))

    def embed(self, texts):
        texts = list(texts)
        for start in range(0, len(texts), 32):
            hidden, attention = self.infer(texts[start : start + 32])
            mask = attention[:, :, None].astype(np.float64)
            pooled = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
            normalized = pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            yield from normalized.astype(hidden.dtype)

    def query_embed(self, query):
        return self.embed([query])


class CrossEncoder(Transformer):
    def __init__(self, directory):
        super().__init__(directory, "onnx/model.onnx", 512)

    def rerank(self, query, passages):
        for start in range(0, len(passages), 16):
            values, _ = self.infer([(query, text) for text in passages[start : start + 16]])
            yield from (float(value) for value in values.reshape(-1))


@dataclass
class SparseVector:
    indices: np.ndarray
    values: np.ndarray


class BM25Encoder:
    """BM25 term weights with Qdrant-side IDF; k=1.2, b=.75, fixed reference length=256."""

    def __init__(self, directory):
        self.stopwords = set((directory / "english.txt").read_text().splitlines())
        self.stemmer = SnowballStemmer("english")

    def tokens(self, text):
        words = re.sub(r"[^\w]", " ", text.lower()).split()
        return [
            stem
            for word in words
            if word not in self.stopwords and len(word) <= 40
            if (stem := self.stemmer.stem_word(word))
        ]

    def embed(self, texts):
        for text in texts:
            tokens = self.tokens(text)
            weights = {
                abs(mmh3.hash(term)): frequency
                * 2.2
                / (frequency + 1.2 * (0.25 + 0.75 * len(tokens) / 256))
                for term, frequency in Counter(tokens).items()
            }
            indices = sorted(weights)
            yield SparseVector(
                np.asarray(indices, dtype=np.int64),
                np.asarray([weights[i] for i in indices], dtype=np.float64),
            )

    def query_embed(self, query):
        indices = sorted({abs(mmh3.hash(term)) for term in self.tokens(query)})
        yield SparseVector(np.asarray(indices, dtype=np.int64), np.ones(len(indices)))
