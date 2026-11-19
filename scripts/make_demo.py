"""Build the offline demo report and the evaluation gold set.

Run from the repo root:
    python scripts/make_demo.py

The demo is deliberately illustrative: real open-access papers, a fictional
citing paper, and hand-curated verdicts. Replace it with a real paper before the
final pitch if you have time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from citeverify.models import Claim, ClaimResult, Confidence, Reference, Report, Verdict
from citeverify.report import build_report

SOURCES = {
    "transformer": {
        "doi": "10.48550/arxiv.1706.03762",
        "url": "https://doi.org/10.48550/arXiv.1706.03762",
        "title": "Attention Is All You Need",
        "authors": [
            "Ashish Vaswani",
            "Noam Shazeer",
            "Niki Parmar",
            "Jakob Uszkoreit",
            "Llion Jones",
            "Aidan N. Gomez",
            "Lukasz Kaiser",
            "Illia Polosukhin",
        ],
        "year": 2017,
        "abstract": (
            "The dominant sequence transduction models are based on complex recurrent or "
            "convolutional neural networks that include an encoder and a decoder. The best "
            "performing models also connect the encoder and decoder through an attention "
            "mechanism. We propose a new simple network architecture, the Transformer, based "
            "solely on attention mechanisms, dispensing with recurrence and convolutions "
            "entirely. Experiments on two machine translation tasks show these models to be "
            "superior in quality while being more parallelizable and requiring significantly "
            "less time to train. Our model achieves 28.4 BLEU on the WMT 2014 English-to-German "
            "translation task, improving over the existing best results, including ensembles, "
            "by over 2 BLEU. On the WMT 2014 English-to-French translation task, our model "
            "establishes a new single-model state-of-the-art BLEU score of 41.8 after training "
            "for 3.5 days on eight GPUs, a small fraction of the training costs of the best "
            "models from the literature. We show that the Transformer generalizes well to other "
            "tasks by applying it successfully to English constituency parsing both with large "
            "and limited training data."
        ),
    },
    "bert": {
        "doi": "10.48550/arxiv.1810.04805",
        "url": "https://doi.org/10.48550/arXiv.1810.04805",
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "authors": ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "Kristina Toutanova"],
        "year": 2019,
        "abstract": (
            "We introduce a new language representation model called BERT, which stands for "
            "Bidirectional Encoder Representations from Transformers. Unlike recent language "
            "representation models, BERT is designed to pre-train deep bidirectional "
            "representations from unlabeled text by jointly conditioning on both left and right "
            "context in all layers. As a result, the pre-trained BERT model can be fine-tuned "
            "with just one additional output layer to create state-of-the-art models for a wide "
            "range of tasks, such as question answering and language inference, without "
            "substantial task-specific architecture modifications. BERT is conceptually simple "
            "and empirically powerful. It obtains new state-of-the-art results on eleven natural "
            "language processing tasks, including pushing the GLUE score to 80.5% (7.7 point "
            "absolute improvement), MultiNLI accuracy to 86.7% (4.6% absolute improvement), "
            "SQuAD v1.1 question answering Test F1 to 93.2 (1.5 point absolute improvement) and "
            "SQuAD v2.0 Test F1 to 83.1 (5.1 point absolute improvement)."
        ),
    },
    "dropout": {
        "doi": "10.48550/arxiv.1207.0580",
        "url": "https://doi.org/10.48550/arXiv.1207.0580",
        "title": "Dropout: A Simple Way to Prevent Neural Networks from Overfitting",
        "authors": [
            "Nitish Srivastava",
            "Geoffrey Hinton",
            "Alex Krizhevsky",
            "Ilya Sutskever",
            "Ruslan Salakhutdinov",
        ],
        "year": 2014,
        "abstract": (
            "Deep neural nets with a large number of parameters are very powerful machine "
            "learning systems. However, overfitting is a serious problem in such networks. Large "
            "networks are also slow to use, making it difficult to deal with overfitting by "
            "combining the predictions of many different large neural nets at test time. Dropout "
            "is a technique for addressing this problem. The key idea is to randomly drop units "
            "(along with their connections) from the neural network during training. This "
            "prevents units from co-adapting too much. During training, dropout samples from an "
            "exponential number of different thinned networks. At test time, it is easy to "
            "approximate the effect of averaging the predictions of all these thinned networks by "
            "simply using a single unthinned network that has smaller weights. This significantly "
            "reduces overfitting and gives major improvements over other regularization methods. "
            "We show that dropout improves the performance of neural networks on supervised "
            "learning tasks in vision, speech recognition, document classification and "
            "computational biology, obtaining state-of-the-art results on many benchmark data sets."
        ),
    },
    "adam": {
        "doi": "10.48550/arxiv.1412.6980",
        "url": "https://doi.org/10.48550/arXiv.1412.6980",
        "title": "Adam: A Method for Stochastic Optimization",
        "authors": ["Diederik P. Kingma", "Jimmy Ba"],
        "year": 2015,
        "abstract": (
            "We introduce Adam, an algorithm for first-order gradient-based optimization of "
            "stochastic objective functions, based on adaptive estimates of lower-order moments. "
            "The method is straightforward to implement, is computationally efficient, has little "
            "memory requirements, is invariant to diagonal rescaling of the gradients, and is well "
            "suited for problems that are large in terms of data and/or parameters. The method is "
            "also appropriate for non-stationary objectives and problems with very noisy and/or "
            "sparse gradients. The hyper-parameters have intuitive interpretations and typically "
            "require little tuning. Some connections to related algorithms are discussed. We also "
            "discuss the relationship between Adam and its variants, and the choice of "
            "hyper-parameters. We analyze the convergence properties of Adam and show that it can "
            "converge to a stationarity point under certain conditions."
        ),
    },
    "gan": {
        "doi": "10.48550/arxiv.1406.2661",
        "url": "https://doi.org/10.48550/arXiv.1406.2661",
        "title": "Generative Adversarial Nets",
        "authors": [
            "Ian J. Goodfellow",
            "Jean Pouget-Abadie",
            "Mehdi Mirza",
            "Bing Xu",
            "David Warde-Farley",
            "Sherjil Ozair",
            "Aaron Courville",
            "Yoshua Bengio",
        ],
        "year": 2014,
        "abstract": (
            "We propose a new framework for estimating generative models via an adversarial "
            "process, in which we simultaneously train two models: a generative model G that "
            "captures the data distribution, and a discriminative model D that estimates the "
            "probability that a sample came from the training data rather than G. The training "
            "procedure for G is to maximize the probability of D making a mistake. This framework "
            "corresponds to a minimax two-player game. In the space of arbitrary functions G and "
            "D, a unique solution exists, with G recovering the training distribution and D equal "
            "to 1/2 everywhere. In the case where G and D are defined by multilayer perceptrons, "
            "the entire system can be trained with backpropagation. There is no need for any "
            "Markov chains or unrolled approximate inference networks during either training or "
            "generation of samples. Experiments demonstrate the potential of the framework through "
            "qualitative and quantitative evaluation of the generated samples."
        ),
    },
    "resnet": {
        "doi": "10.48550/arxiv.1512.03385",
        "url": "https://doi.org/10.48550/arXiv.1512.03385",
        "title": "Deep Residual Learning for Image Recognition",
        "authors": ["Kaiming He", "Xiangyu Zhang", "Shaoqing Ren", "Jian Sun"],
        "year": 2016,
        "abstract": (
            "Deeper neural networks are more difficult to train. We present a residual learning "
            "framework to ease the training of networks that are substantially deeper than those "
            "used previously. We explicitly reformulate the layers as learning residual functions "
            "with reference to the layer inputs, instead of learning unreferenced functions. We "
            "provide comprehensive empirical evidence showing that these residual networks are "
            "easier to optimize, and can gain accuracy from considerably increased depth. On the "
            "ImageNet dataset we evaluate residual nets with a depth of up to 152 layers—8x deeper "
            "than VGG nets but still having lower complexity. An ensemble of these residual nets "
            "achieves 3.57% error on the ImageNet test set. This result won the 1st place on the "
            "ILSVRC 2015 classification task. We also present analysis on CIFAR-10 with 100 and "
            "1000 layers."
        ),
    },
}


def reference(key: str, ref_id: str) -> Reference:
    source = SOURCES[key]
    return Reference(
        id=ref_id,
        raw=f"{source['authors'][0]} et al. ({source['year']}). {source['title']}.",
        doi=source["doi"],
        title=source["title"],
        authors=source["authors"],
        year=source["year"],
        url=source["url"],
        abstract=source["abstract"],
        resolved=True,
        provider="demo",
        match_score=100.0,
    )


CASES = [
    {
        "claim": "The Transformer architecture relies on recurrence and convolution to process sequences.",
        "section": "Introduction",
        "marker": "[1]",
        "source": "transformer",
        "verdict": Verdict.CONTRADICTED,
        "confidence": Confidence.HIGH,
        "quote": (
            "We propose a new simple network architecture, the Transformer, based solely on "
            "attention mechanisms, dispensing with recurrence and convolutions entirely."
        ),
        "reason": (
            "The cited paper explicitly says the Transformer dispenses with recurrence and "
            "convolutions entirely."
        ),
        "fix": (
            "Rewrite as: 'The Transformer relies solely on attention mechanisms, dispensing with "
            "recurrence and convolutions.'"
        ),
    },
    {
        "claim": "BERT is pre-trained using a unidirectional language model.",
        "section": "Related work",
        "marker": "[2]",
        "source": "bert",
        "verdict": Verdict.CONTRADICTED,
        "confidence": Confidence.HIGH,
        "quote": (
            "BERT is designed to pre-train deep bidirectional representations from unlabeled text "
            "by jointly conditioning on both left and right context in all layers."
        ),
        "reason": "BERT is explicitly bidirectional, not unidirectional.",
        "fix": "Change 'unidirectional' to 'bidirectional'.",
    },
    {
        "claim": "Dropout prevents units from co-adapting too much during training.",
        "section": "Method",
        "marker": "[3]",
        "source": "dropout",
        "verdict": Verdict.SUPPORTED,
        "confidence": Confidence.HIGH,
        "quote": "This prevents units from co-adapting too much.",
        "reason": "The source directly states the claim.",
        "fix": None,
    },
    {
        "claim": "Dropout eliminates overfitting in deep neural networks.",
        "section": "Discussion",
        "marker": "[3]",
        "source": "dropout",
        "verdict": Verdict.PARTIALLY_SUPPORTED,
        "confidence": Confidence.HIGH,
        "quote": (
            "This significantly reduces overfitting and gives major improvements over other "
            "regularization methods."
        ),
        "reason": "The source says dropout significantly reduces overfitting, not that it eliminates it.",
        "fix": "Soften 'eliminates' to 'significantly reduces'.",
    },
    {
        "claim": "Adam is appropriate for problems with very noisy and/or sparse gradients.",
        "section": "Introduction",
        "marker": "[4]",
        "source": "adam",
        "verdict": Verdict.SUPPORTED,
        "confidence": Confidence.HIGH,
        "quote": (
            "The method is also appropriate for non-stationary objectives and problems with very "
            "noisy and/or sparse gradients."
        ),
        "reason": "The source directly states that Adam is appropriate for these problems.",
        "fix": None,
    },
    {
        "claim": (
            "GANs train a discriminator to estimate whether a sample came from the training data "
            "rather than the generator."
        ),
        "section": "Method",
        "marker": "[5]",
        "source": "gan",
        "verdict": Verdict.SUPPORTED,
        "confidence": Confidence.HIGH,
        "quote": (
            "a discriminative model D that estimates the probability that a sample came from the "
            "training data rather than G."
        ),
        "reason": "The source describes exactly this discriminator objective.",
        "fix": None,
    },
    {
        "claim": (
            "Residual networks are easier to optimize and can gain accuracy from considerably "
            "increased depth."
        ),
        "section": "Results",
        "marker": "[6]",
        "source": "resnet",
        "verdict": Verdict.SUPPORTED,
        "confidence": Confidence.HIGH,
        "quote": (
            "We provide comprehensive empirical evidence showing that these residual networks are "
            "easier to optimize, and can gain accuracy from considerably increased depth."
        ),
        "reason": "The source directly reports this empirical result.",
        "fix": None,
    },
    {
        "claim": "The Transformer was evaluated on image classification benchmarks.",
        "section": "Experiments",
        "marker": "[1]",
        "source": "transformer",
        "verdict": Verdict.UNSUPPORTED,
        "confidence": Confidence.MEDIUM,
        "quote": (
            "Experiments on two machine translation tasks show these models to be superior in "
            "quality while being more parallelizable and requiring significantly less time to train."
        ),
        "reason": (
            "The abstract scopes its experiments to machine translation. It provides no evidence "
            "of image classification."
        ),
        "fix": "Cite an image-classification evaluation or remove the claim.",
    },
    {
        "claim": "Increasing depth in residual networks always improves accuracy.",
        "section": "Discussion",
        "marker": "[6]",
        "source": "resnet",
        "verdict": Verdict.PARTIALLY_SUPPORTED,
        "confidence": Confidence.HIGH,
        "quote": (
            "We provide comprehensive empirical evidence showing that these residual networks are "
            "easier to optimize, and can gain accuracy from considerably increased depth."
        ),
        "reason": "The source says 'can gain accuracy', not that accuracy always improves.",
        "fix": "Replace 'always improves' with 'can improve'.",
    },
    {
        "claim": "BERT was trained on a corpus of one trillion words.",
        "section": "Training details",
        "marker": "[2]",
        "source": "bert",
        "verdict": Verdict.UNVERIFIABLE,
        "confidence": Confidence.LOW,
        "quote": None,
        "reason": "The abstract does not report corpus size; the full text is needed.",
        "fix": "Cite the training-data section or remove the number.",
    },
]


def main() -> None:
    data_dir = ROOT / "data"
    demo_dir = data_dir / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)

    results: list[ClaimResult] = []
    gold_cases: list[dict] = []

    for index, case in enumerate(CASES, start=1):
        ref = reference(case["source"], f"ref_{index}")
        claim = Claim(
            id=f"claim_{index}",
            text=case["claim"],
            section=case["section"],
            citation_marker=case["marker"],
            reference_id=ref.id,
            page=1,
        )
        results.append(
            ClaimResult(
                claim=claim,
                reference=ref,
                verdict=case["verdict"],
                confidence=case["confidence"],
                evidence_quote=case["quote"],
                reason=case["reason"],
                suggested_fix=case["fix"],
                source_url=ref.url,
                source_title=ref.title,
                source_year=ref.year,
                flags=[],
            )
        )
        gold_cases.append(
            {
                "id": f"gold_{index}",
                "claim": {
                    "id": f"gold_claim_{index}",
                    "text": case["claim"],
                    "section": case["section"],
                    "citation_marker": case["marker"],
                    "reference_id": "source",
                },
                "source": {
                    "doi": ref.doi,
                    "url": ref.url,
                    "title": ref.title,
                    "authors": ref.authors,
                    "year": ref.year,
                    "abstract": ref.abstract,
                },
                "expected_verdict": case["verdict"].value,
                "expected_evidence_contains": case["quote"],
            }
        )

    report = build_report(
        "Illustrative Demo Paper: Foundations of Modern AI",
        "demo_paper.pdf",
        results,
        mode="demo",
    )
    (demo_dir / "demo_report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )

    gold_set = {
        "description": (
            "Hand-labelled demo claims over real open-access abstracts. This is a "
            "sanity-check set, not a benchmark. Run scripts/evaluate.py with an LLM key."
        ),
        "cases": gold_cases,
    }
    (data_dir / "gold_set.json").write_text(
        json.dumps(gold_set, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Wrote {demo_dir / 'demo_report.json'}")
    print(f"Wrote {data_dir / 'gold_set.json'}")
    print(f"Claims: {len(results)}")


if __name__ == "__main__":
    main()
