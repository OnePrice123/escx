"""Жёсткий лимит расходов — в коде, а не в дашборде.

Дашборд сообщает о перерасходе постфактум. Единственное, что реально
останавливает счёт, — исключение в момент превышения. Лимит персистится в SQLite,
поэтому переживает перезапуск процесса и работает в GitHub Actions,
где каждый прогон стартует с чистого листа.
"""
from __future__ import annotations
import sqlite3
from datetime import date

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_spend (
  day        TEXT NOT NULL,
  model      TEXT NOT NULL,
  calls      INTEGER NOT NULL DEFAULT 0,
  tok_in     INTEGER NOT NULL DEFAULT 0,
  tok_out    INTEGER NOT NULL DEFAULT 0,
  usd        REAL    NOT NULL DEFAULT 0,
  PRIMARY KEY (day, model)
);
"""


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """Учёт токенов и денег с дневным потолком.

    prices: {'модель': (usd за 1M входных, usd за 1M выходных)}
    """

    def __init__(self, con: sqlite3.Connection, *, daily_usd: float = 3.0,
                 prices: dict[str, tuple[float, float]] | None = None):
        self.con = con
        self.daily = daily_usd
        self.prices = prices or {}
        con.executescript(SCHEMA)

    def spent_today(self) -> float:
        r = self.con.execute("SELECT COALESCE(SUM(usd),0) s FROM llm_spend WHERE day=?",
                             (date.today().isoformat(),)).fetchone()
        return float(r[0])

    def remaining(self) -> float:
        return max(0.0, self.daily - self.spent_today())

    def cost(self, model: str, tok_in: int, tok_out: int) -> float:
        pin, pout = self.prices.get(model, (0.0, 0.0))
        return tok_in / 1e6 * pin + tok_out / 1e6 * pout

    def check(self, model: str, est_in: int, est_out: int) -> None:
        """Вызывается ПЕРЕД запросом. Оценка сверху, а не по факту."""
        if self.spent_today() + self.cost(model, est_in, est_out) > self.daily:
            raise BudgetExceeded(
                f"дневной лимит ${self.daily:.2f} исчерпан "
                f"(потрачено ${self.spent_today():.4f}); прогон остановлен")

    def record(self, model: str, tok_in: int, tok_out: int) -> float:
        usd = self.cost(model, tok_in, tok_out)
        self.con.execute(
            "INSERT INTO llm_spend(day,model,calls,tok_in,tok_out,usd) VALUES(?,?,1,?,?,?) "
            "ON CONFLICT(day,model) DO UPDATE SET calls=calls+1, tok_in=tok_in+excluded.tok_in, "
            "tok_out=tok_out+excluded.tok_out, usd=usd+excluded.usd",
            (date.today().isoformat(), model, tok_in, tok_out, usd))
        self.con.commit()
        return usd

    def report(self) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM llm_spend ORDER BY day DESC, usd DESC LIMIT 30")]
