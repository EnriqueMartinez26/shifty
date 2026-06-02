from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass(frozen=True)
class TimeSlot:
    """Immutable value object representing a time period with a start and end."""
    start_time: datetime
    end_time: datetime

    def __post_init__(self):
        if self.start_time >= self.end_time:
            raise ValueError("Start time must be before end_time")

    @property
    def duration_minutes(self) -> int:
        delta = self.end_time - self.start_time
        return int(delta.total_seconds() / 60)

    def overlaps_with(self, other: 'TimeSlot') -> bool:
        """Check if this time slot overlaps with another."""
        return self.start_time < other.end_time and other.start_time < self.end_time

    def contains(self, time: datetime) -> bool:
        """Check if a specific time is within this time slot."""
        return self.start_time <= time < self.end_time

    @classmethod
    def from_start_and_duration(cls, start_time: datetime, duration_minutes: int) -> 'TimeSlot':
        """Factory method to create a TimeSlot from a start time and duration."""
        end_time = start_time + timedelta(minutes=duration_minutes)
        return cls(start_time, end_time)

    def to_dict(self):
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_minutes": self.duration_minutes
        }
