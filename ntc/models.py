from dataclasses import dataclass, field, asdict


@dataclass
class CellRead:
    row: int
    col: int
    name: str
    raw_ocr: str
    qty: int
    flags: list = field(default_factory=list)


@dataclass
class ScanResult:
    started_at: str
    kind: str = "cabinet"          # which window was scanned: "cabinet" | "inventory"
    duration_s: float = 0.0
    aborted: bool = False
    cells: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def recompute(self):
        totals = {}
        for c in self.cells:
            totals[c.name] = totals.get(c.name, 0) + c.qty
        self.totals = dict(sorted(totals.items()))

    def to_dict(self):
        return asdict(self)
