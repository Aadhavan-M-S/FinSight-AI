import math
import re
import string
from decimal import Decimal, DecimalException, localcontext
from typing import Literal

from pydantic import BaseModel, Field

from ..financial import parse_number

SCALE = {
    "": Decimal(1),
    "hundred": Decimal(100),
    "thousand": Decimal(1000),
    "million": Decimal(10**6),
    "billion": Decimal(10**9),
    "percent": Decimal("0.01"),
}
QUANTITY = re.compile(
    r"^\s*(?P<currency>USD|EUR|GBP|INR|\$|€|£|₹)?\s*"
    r"(?P<value>\(?[-+−]?(?:[\d,]+(?:\.\d+)?|\.\d+)\)?)\s*"
    r"(?P<scale>%|percent|hundred|thousand|million|billion)?\s*"
    r"(?P<currency2>USD|EUR|GBP|INR)?\s*$",
    re.I,
)
OPERATION = Literal[
    "add",
    "subtract",
    "multiply",
    "divide",
    "exp",
    "greater",
    "sum",
    "average",
    "min",
    "max",
    "count",
]
ANSWER_SCALE = Literal["", "hundred", "thousand", "million", "billion", "percent"]


class Step(BaseModel):
    operation: OPERATION
    operands: list[str] = Field(min_length=1, max_length=30)


class Prediction(BaseModel):
    answer: str | list[str] | None = None
    scale: ANSWER_SCALE = ""
    program: list[Step] = Field(default_factory=list, max_length=12)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


def retrieval_metrics(ranked, relevant, k):
    if not relevant:
        return {}
    matches = [i for i, identifier in enumerate(ranked[:k], 1) if identifier in relevant]
    dcg = sum(1 / math.log2(i + 1) for i in matches)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(relevant)) + 1))
    return {
        f"recall@{k}": len(matches) / len(relevant),
        f"mrr@{k}": 1 / matches[0] if matches else 0,
        f"ndcg@{k}": dcg / ideal,
    }


def quantity(value, declared_scale=""):
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        return None
    match = QUANTITY.fullmatch(str(value))
    if not match:
        return None
    raw = match["value"].replace(" ", "").replace("+", "")
    if raw.startswith("."):
        raw = "0" + raw
    elif raw.startswith("-."):
        raw = "-0" + raw[1:]
    parsed = parse_number(raw)
    if parsed is None:
        return None
    scale = (match["scale"] or declared_scale or "").casefold()
    scale = "percent" if scale == "%" else scale
    unit = (match["currency"] or match["currency2"] or "").upper()
    unit = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}.get(unit, unit)
    return parsed * SCALE.get(scale, Decimal(1)), unit, scale


def operand_number(raw, results):
    raw = raw.strip()
    if re.fullmatch(r"#\d{1,2}", raw):
        index = int(raw[1:])
        if index >= len(results) or not isinstance(results[index], Decimal):
            raise ValueError("A program reference does not point to an earlier numerical step.")
        return results[index]
    if raw.startswith("const_"):
        raw = raw.removeprefix("const_")
        raw = "-1" if raw == "m1" else raw
    if len(raw) > 40:
        raise ValueError("Program operand exceeds the allowed length.")
    value = quantity(raw)
    if value is None or abs(value[0]) > Decimal("1e24"):
        raise ValueError("The program includes an invalid or out-of-range numeric operand.")
    return value[0]


def evaluate_program(steps):
    results = []
    operations = {
        "add": lambda a, b: a + b,
        "subtract": lambda a, b: a - b,
        "multiply": lambda a, b: a * b,
        "divide": lambda a, b: a / b,
        "exp": lambda a, b: a**b,
        "greater": lambda a, b: "yes" if a > b else "no",
    }
    aggregates = {
        "sum": sum,
        "average": lambda values: sum(values) / len(values),
        "min": min,
        "max": max,
        "count": lambda values: Decimal(len(values)),
    }
    with localcontext() as ctx:
        ctx.prec = 32
        for index, step in enumerate(steps):
            values = [operand_number(value, results) for value in step.operands]
            if step.operation in operations:
                if len(values) != 2:
                    raise ValueError("Binary operations require exactly two operands.")
                if step.operation == "exp" and (values[1] != int(values[1]) or abs(values[1]) > 12):
                    raise ValueError("Only bounded integer exponents are supported.")
                result = operations[step.operation](*values)
            else:
                result = aggregates[step.operation](values)
            if isinstance(result, Decimal):
                if not result.is_finite() or abs(result) > Decimal("1e28"):
                    raise ValueError("The program result exceeds supported numerical bounds.")
            elif index < len(steps) - 1:
                raise ValueError("A comparison may only be used as the final step.")
            results.append(result)
    value = results[-1]
    return format(value.normalize(), "f") if isinstance(value, Decimal) else value


def normalized_text(answer):
    words = []
    for token in str(answer).casefold().split():
        parsed = quantity(token)
        if parsed:
            words.append(format(parsed[0].normalize(), "f"))
        else:
            word = token.translate(str.maketrans("", "", string.punctuation))
            if word and word not in {"a", "an", "the"}:
                words.append(word)
    return " ".join(words)


def inputs(answer):
    if answer is None:
        return []
    return answer if isinstance(answer, list) else [answer]


def tatqa_text(answer, scale):
    parts = []
    for value in sorted(map(str, inputs(answer))):
        number = quantity(value, scale)
        if number:
            scalar = number[0]
            if "%" not in value:
                factor = SCALE[number[2]]
                scalar = round(scalar / factor, 2) * factor
            parts.append(format(round(scalar, 4), "f"))
        else:
            parts.append((value + " " + (scale or "")).strip())
    return normalized_text(" ".join(parts))


def tatqa_metrics(record, prediction, answer):
    gold = tatqa_text(record.gold_answer, record.metadata.get("scale"))
    candidate = tatqa_text(answer, prediction.scale)
    a, b = set(candidate.split()), set(gold.split())
    return {
        "tatqa_em": float(candidate == gold and bool(candidate)),
        "tatqa_f1": round(2 * len(a & b) / (len(a) + len(b)), 2) if a and b else 0.0,
    }


def single_value(answer):
    if isinstance(answer, list):
        return answer[0] if len(answer) == 1 else None
    return answer


def numeric_match(gold, answer, scale="", gold_scale="", decimals=5, question=""):
    gold, guess = quantity(single_value(gold), gold_scale), quantity(single_value(answer), scale)
    if gold is None:
        return None
    if guess is None:
        return 0.0
    if gold[1] and guess[1] and gold[1] != guess[1]:
        return 0.0
    gv, pv = gold[0], guess[0]
    # FinanceBench frequently expresses the denominator in the question rather than the reference.
    unit_hint = re.search(
        r"\bin\s+(?:(?:USD|EUR|GBP|INR)\s+)?(thousands|millions|billions)\b", question, re.I
    )
    if unit_hint and bool(gold[2]) != bool(guess[2]):
        multiplier = SCALE[unit_hint[1].lower().rstrip("s")]
        if not gold[2]:
            gv *= multiplier
        if not guess[2]:
            pv *= multiplier
    try:
        return float(round(gv, decimals) == round(pv, decimals))
    except DecimalException:
        return 0.0


def answer_metrics(record, prediction, answer):
    if record.dataset_id == "tatqa":
        return tatqa_metrics(record, prediction, answer)
    gold = record.gold_answer
    guess = single_value(answer)
    if record.dataset_id in {"finqa", "convfinqa", "docfinqa"}:
        reference = record.metadata.get("execution_answer")
        value = numeric_match(reference if reference is not None else gold, guess, prediction.scale)
        if value is not None:
            return {"execution_value_match_5dp": value}
        return {
            "answer_exact_match": float(bool(guess) and normalized_text(guess) == normalized_text(gold))
        }
    if record.dataset_id == "multihiertt":
        gold_text, predicted = normalized_text(gold), normalized_text(guess or "")
        a, b = set(gold_text.split()), set(predicted.split())
        return {
            "answer_exact_match": float(bool(predicted) and predicted == gold_text),
            "answer_token_f1": 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0,
        }
    metrics = {"answer_exact_match": float(bool(guess) and normalized_text(guess) == normalized_text(gold))}
    numeric = numeric_match(gold, guess, prediction.scale, question=record.question)
    if numeric is not None:
        metrics["numeric_match"] = numeric
    return metrics
