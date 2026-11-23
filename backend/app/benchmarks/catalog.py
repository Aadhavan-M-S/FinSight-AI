from dataclasses import dataclass, field

MIB = 1024 * 1024
GITHUB = "https://github.com/"
RAW = "https://raw.githubusercontent.com/"
HF = "https://huggingface.co/datasets/"


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str
    description: str
    task_type: str
    source: str
    citation: str
    terms: str
    terms_url: str
    tasks: dict[str, str]
    splits: dict[str, str]
    limits: str
    repo: str | None = None
    revision: str | None = None
    hub: str | None = None
    max_download: int = 64 * MIB
    archive: str | None = None
    files: dict[str, str] = field(default_factory=dict)
    noncommercial: bool = False

    def raw(self, path: str) -> str:
        return f"{RAW}{self.repo}/{self.revision}/{path}"


FINANCE = "patronus-ai/financebench"
FINANCE_REV = "cc39aeb4afdf33909ee1412188bf89035950c2eb"
MULTI_DOWNLOAD = "https://drive.google.com/drive/folders/1ituEWZ5F7G9T9AZ0kzZZLrHNhRigHCZJ"
CATALOG = {
    d.id: d
    for d in [
        Dataset(
            "finder",
            "FinDER",
            "Financial evidence retrieval and grounded question answering.",
            "Evidence retrieval and QA",
            HF + "Linq-AI-Research/FinDER",
            HF + "Linq-AI-Research/FinDER",
            "See the publisher’s current dataset card for licensing and citation.",
            HF + "Linq-AI-Research/FinDER",
            {},
            {},
            "Evidence annotations are browsable. Evaluation requires a separately supplied candidate corpus.",
            hub="Linq-AI-Research/FinDER",
        ),
        Dataset(
            "financebench",
            "FinanceBench",
            "The public 150-question release over company filings.",
            "Filing retrieval and grounded QA",
            HF + "PatronusAI/financebench",
            "https://arxiv.org/abs/2311.11944",
            "Noncommercial use only. Review the publisher’s terms and the filing owners’ terms.",
            HF + "PatronusAI/financebench",
            {"retrieval": "Retrieval over official PDF pages", "qa": "PDF-based question answering"},
            {"open_source": "Public annotated release"},
            "Includes source PDF links where available. Evaluation fetches required PDFs on demand.",
            repo=FINANCE,
            revision=FINANCE_REV,
            noncommercial=True,
            files={"open_source": "data/financebench_open_source.jsonl"},
        ),
        Dataset(
            "finqa",
            "FinQA",
            "Numerical questions over financial tables and surrounding filing text.",
            "Numerical reasoning and retrieval",
            GITHUB + "czyssrs/FinQA",
            "https://arxiv.org/abs/2109.00122",
            "Official repository includes an MIT license.",
            GITHUB + "czyssrs/FinQA/blob/main/LICENSE",
            {
                "retrieval": "Retrieval over table rows and text",
                "numerical": "Numerical reasoning from report excerpts",
            },
            {
                "train": "Training",
                "dev": "Development",
                "test": "Public test",
                "private_test": "Private test inputs",
            },
            "Table-and-text protocol. Private test references are absent.",
            repo="czyssrs/FinQA",
            revision="0f16e2867befa6840783e58be38c9efb9229d742",
            files={x: f"dataset/{x}.json" for x in ("train", "dev", "test", "private_test")},
            max_download=96 * MIB,
        ),
        Dataset(
            "tatqa",
            "TAT-QA",
            "Questions over hybrid tabular and textual financial report contexts.",
            "Table-and-text QA",
            GITHUB + "NExTplusplus/TAT-QA",
            "https://aclanthology.org/2021.acl-long.254/",
            "CC BY 4.0 dataset.",
            GITHUB + "NExTplusplus/TAT-QA#license",
            {"qa": "Table-and-text QA", "numerical": "Arithmetic and counting questions"},
            {"train": "Training", "dev": "Development", "test": "Test with publisher-released gold"},
            "Structured excerpts with scale and answer-type annotations.",
            repo="NExTplusplus/TAT-QA",
            revision="870accc41953dcde885aabeb963d94aabdc0fbc3",
            files={
                x: f"dataset_raw/tatqa_dataset_{x}{'_gold' if x == 'test' else ''}.json"
                for x in ("train", "dev", "test")
            },
        ),
        Dataset(
            "convfinqa",
            "ConvFinQA",
            "Financial numerical reasoning across conversation turns.",
            "Conversational numerical reasoning",
            GITHUB + "czyssrs/ConvFinQA",
            "https://arxiv.org/abs/2210.03849",
            "Official repository includes an MIT license.",
            GITHUB + "czyssrs/ConvFinQA/blob/main/LICENSE",
            {"numerical": "Turn-by-turn reasoning with earlier questions"},
            {"train": "Training", "dev": "Development", "test": "Private test inputs"},
            "The archive contains all official splits. Only the selected split is parsed. Test references are absent.",
            repo="czyssrs/ConvFinQA",
            revision="cf3eed2d5984960bf06bb8145bcea5e80b0222a6",
            archive="data.zip",
            files={"train": "data/train.json", "dev": "data/dev.json", "test": "data/test_private.json"},
        ),
        Dataset(
            "docfinqa",
            "DocFinQA",
            "Financial numerical questions with long source documents.",
            "Long-document reasoning",
            HF + "kensho/DocFinQA",
            "https://arxiv.org/abs/2401.06991",
            "See the publisher’s current dataset card for licensing and citation.",
            HF + "kensho/DocFinQA",
            {"numerical": "Numerical reasoning over independently supplied source text"},
            {},
            "Large dataset. Select one split and review its download size. Splits over the local limit can be imported in publisher-provided form if within the limit.",
            hub="kensho/DocFinQA",
            max_download=512 * MIB,
        ),
        Dataset(
            "multihiertt",
            "MultiHiertt",
            "Numerical reasoning over hierarchical tables and related paragraphs.",
            "Multi-table numerical reasoning",
            GITHUB + "psunlpgroup/MultiHiertt",
            "https://aclanthology.org/2022.acl-long.454/",
            "Official repository includes an MIT license.",
            GITHUB + "psunlpgroup/MultiHiertt/blob/main/LICENSE",
            {
                "retrieval": "Retrieval over table facts and paragraphs",
                "numerical": "Multi-table numerical reasoning",
            },
            {"train": "Training", "dev": "Development", "test": "Test inputs"},
            "The official release is shared as a Drive folder. Download the publisher’s JSON split and import it.",
            repo="psunlpgroup/MultiHiertt",
            revision="45bd9ccdf3142ea059bd5e69c0afb83437fa539c",
            max_download=128 * MIB,
        ),
    ]
}
