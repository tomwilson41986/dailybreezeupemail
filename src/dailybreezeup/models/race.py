from datetime import date, time
from typing import Literal

from pydantic import BaseModel

Country = Literal["GB", "IE", "FR"]


class Runner(BaseModel):
    horse: str
    age: int | None = None
    sex: str | None = None
    trainer: str | None = None
    jockey: str | None = None
    owner: str | None = None
    draw: str | None = None
    number: str | None = None
    weight: str | None = None
    form: str | None = None
    sire: str | None = None
    dam: str | None = None
    bred: str | None = None
    finishing_position: str | None = None
    sp: str | None = None
    beaten_lengths: str | None = None


class RaceCard(BaseModel):
    race_id: str
    country: Country
    course: str
    race_date: date
    off_time: time | None = None
    race_name: str
    runners: list[Runner]
    url: str | None = None


class RaceResult(RaceCard):
    pass
