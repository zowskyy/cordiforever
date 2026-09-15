from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class DateResult:
    success: bool
    result: str = ""
    steps: list[str] = field(default_factory=list)
    error: str | None = None
    operation: str | None = None


class DateTimeEnginePlugin(EventDrivenPlugin):
    name = "datetime_engine"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def compute(self, operation: str, **kwargs: Any) -> DateResult:
        try:
            if operation == "today":
                return self._today()
            elif operation == "tomorrow":
                return self._tomorrow()
            elif operation == "yesterday":
                return self._yesterday()
            elif operation == "add_days":
                return self._add_days(**kwargs)
            elif operation == "add_months":
                return self._add_months(**kwargs)
            elif operation == "add_years":
                return self._add_years(**kwargs)
            elif operation == "days_between":
                return self._days_between(**kwargs)
            elif operation == "weekday":
                return self._weekday(**kwargs)
            elif operation == "format":
                return self._format_date(**kwargs)
            else:
                return DateResult(success=False, error=f"Unknown datetime operation: {operation}")
        except Exception as exc:
            return DateResult(success=False, error=str(exc), operation=operation)

    def _parse_date(self, date_str: str) -> datetime:
        date_str = date_str.strip().lower()
        if date_str in ("today", "now"):
            return datetime.now()
        if date_str == "tomorrow":
            return datetime.now() + timedelta(days=1)
        if date_str == "yesterday":
            return datetime.now() - timedelta(days=1)
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return datetime.strptime(date_str, "%Y-%m-%d")

    def _today(self) -> DateResult:
        now = datetime.now()
        return DateResult(success=True, result=now.strftime("%Y-%m-%d"), steps=[f"Today is {now.strftime('%Y-%m-%d')}"], operation="today")

    def _tomorrow(self) -> DateResult:
        now = datetime.now() + timedelta(days=1)
        return DateResult(success=True, result=now.strftime("%Y-%m-%d"), steps=[f"Tomorrow is {now.strftime('%Y-%m-%d')}"], operation="tomorrow")

    def _yesterday(self) -> DateResult:
        now = datetime.now() - timedelta(days=1)
        return DateResult(success=True, result=now.strftime("%Y-%m-%d"), steps=[f"Yesterday was {now.strftime('%Y-%m-%d')}"], operation="yesterday")

    def _add_days(self, **kwargs: Any) -> DateResult:
        date = self._parse_date(kwargs["date"])
        days = int(kwargs["days"])
        result = date + timedelta(days=days)
        return DateResult(success=True, result=result.strftime("%Y-%m-%d"), steps=[f"{date.strftime('%Y-%m-%d')} + {days} days = {result.strftime('%Y-%m-%d')}"], operation="add_days")

    def _add_months(self, **kwargs: Any) -> DateResult:
        from dateutil.relativedelta import relativedelta
        date = self._parse_date(kwargs["date"])
        months = int(kwargs["months"])
        result = date + relativedelta(months=months)
        return DateResult(success=True, result=result.strftime("%Y-%m-%d"), steps=[f"{date.strftime('%Y-%m-%d')} + {months} months = {result.strftime('%Y-%m-%d')}"], operation="add_months")

    def _add_years(self, **kwargs: Any) -> DateResult:
        from dateutil.relativedelta import relativedelta
        date = self._parse_date(kwargs["date"])
        years = int(kwargs["years"])
        result = date + relativedelta(years=years)
        return DateResult(success=True, result=result.strftime("%Y-%m-%d"), steps=[f"{date.strftime('%Y-%m-%d')} + {years} years = {result.strftime('%Y-%m-%d')}"], operation="add_years")

    def _days_between(self, **kwargs: Any) -> DateResult:
        start = self._parse_date(kwargs["start"])
        end = self._parse_date(kwargs["end"])
        delta = abs((end - start).days)
        return DateResult(success=True, result=str(delta), steps=[f"Days between {start.strftime('%Y-%m-%d')} and {end.strftime('%Y-%m-%d')} = {delta}"], operation="days_between")

    def _weekday(self, **kwargs: Any) -> DateResult:
        date = self._parse_date(kwargs["date"])
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day = days[date.weekday()]
        return DateResult(success=True, result=day, steps=[f"{date.strftime('%Y-%m-%d')} is a {day}"], operation="weekday")

    def _format_date(self, **kwargs: Any) -> DateResult:
        date = self._parse_date(kwargs["date"])
        fmt = kwargs.get("format", "%Y-%m-%d")
        try:
            result = date.strftime(fmt)
        except Exception as exc:
            return DateResult(success=False, error=str(exc), operation="format")
        return DateResult(success=True, result=result, steps=[f"Format {date.strftime('%Y-%m-%d')} as '{fmt}' = {result}"], operation="format")

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass
