from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalSample:
    query: str
    positives: list[str]
    negatives: list[str] = field(default_factory=list)
    filters: dict | None = None


@dataclass(frozen=True)
class EvalDataset:
    name: str
    samples: list[EvalSample]


def build_dataset(name: str, raw_items: list[dict]) -> EvalDataset:
    samples: list[EvalSample] = []
    for item in raw_items:
        query = str(item.get("query") or "").strip()
        positives = [str(v).strip() for v in item.get("positives") or [] if str(v).strip()]
        negatives = [str(v).strip() for v in item.get("negatives") or [] if str(v).strip()]
        if not query or not positives:
            continue
        samples.append(
            EvalSample(
                query=query,
                positives=positives,
                negatives=negatives,
                filters=item.get("filters"),
            )
        )
    return EvalDataset(name=name, samples=samples)
